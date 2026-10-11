"""Verified whole-device NVIDIA/Ascend providers and five-minute monitoring.

Ascend metric names/units and physical labels:
https://github.com/Ascend/mind-cluster/blob/master/docs/zh/scheduling/06_api/00_npu_exporter/01_prometheus_metrics_api.md
NVIDIA metric units:
https://github.com/NVIDIA/dcgm-exporter/blob/main/etc/dcp-metrics-included.csv
"""
import math
import os
import re

PROVIDERS = {
    "nvidia": {"resource_keys": ("nvidia.com/gpu",),
               "metrics": {"utilization": "DCGM_FI_DEV_GPU_UTIL", "memory_used": "DCGM_FI_DEV_FB_USED", "memory_total": "DCGM_FI_DEV_FB_TOTAL"},
               "memory_unit": "MiB", "monitor_source": "prometheus-dcgm"},
    "ascend": {"resource_keys": ("huawei.com/Ascend310P",),
               "metrics": {"utilization": 'npu_chip_info_utilization{job="npu-exporter"}', "memory_used": 'npu_chip_info_used_memory{job="npu-exporter"}', "memory_total": 'npu_chip_info_total_memory{job="npu-exporter"}'},
               "memory_unit": "MB", "monitor_source": "prometheus-npu-exporter"},
}
MONITOR_WINDOW_SECONDS = 300
BUSINESS_OWNER_LABELS = frozenset(("exported_container", "exported_namespace", "exported_pod"))


def resource_keys(vendor):
    if vendor == "nvidia":
        return (os.getenv("GPU_ALLOCATION_PHYSICAL_RESOURCE_KEY", "nvidia.com/gpu"),)
    raw = os.getenv("GPU_ALLOCATION_ASCEND_PHYSICAL_RESOURCE_KEYS", "huawei.com/Ascend310P")
    keys = tuple(dict.fromkeys(key.strip() for key in raw.split(",") if key.strip()))
    if not keys or any(not re.fullmatch(r"huawei\.com/Ascend(?:310P|910[A-Z]?)", key) for key in keys):
        raise ValueError("unverified_ascend_resource_key")
    return keys


def _identity(metric, node, vendor):
    if vendor == "nvidia":
        uuid = str(metric.get("UUID") or "").strip()
        if not uuid.upper().startswith("GPU-") or metric.get("GPU_I_ID") not in (None, "", "-1"):
            raise ValueError("physical_device_identity_invalid")
        return (node, uuid), uuid
    if str(metric.get("is_virtual", "false")).lower() in ("true", "1") or metric.get("v_dev_id") not in (None, "", "-1"):
        raise ValueError("virtual_ascend_device")
    identifier = str(metric.get("id") if metric.get("id") is not None else "").strip()
    pci = str(metric.get("pcie_bus_info") or "").strip().lower()
    if identifier and not re.fullmatch(r"\d+", identifier):
        raise ValueError("physical_device_identity_invalid")
    if pci and not re.fullmatch(r"[0-9a-f]{4,8}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", pci):
        raise ValueError("physical_device_identity_invalid")
    # vdie_id is a UUID in the official physical exporter, but alone does not
    # establish whether the series describes a chip or a virtual partition.
    if not identifier and not pci:
        raise ValueError("physical_device_identity_missing")
    key = (node, ("pci:" + pci) if pci else ("id:" + identifier))
    return key, str(metric.get("vdie_id") or "").strip()


def _memory_multiplier(vendor):
    units = {"bytes": 1, "KB": 1000, "KiB": 1024, "MB": 1000**2, "MiB": 1024**2, "GB": 1000**3, "GiB": 1024**3}
    return units.get(os.getenv("GPU_ALLOCATION_" + vendor.upper() + "_MEMORY_UNIT", PROVIDERS[vendor]["memory_unit"]))


def _monitor_queries(timestamp, vendor="nvidia"):
    # An instant-query range selector returns the real scrape timestamps. An
    # avg_over_time result alone cannot prove that a whole five-minute window
    # exists (a newly added card could have only one data point).
    queries = {}
    for name, default in PROVIDERS[vendor]["metrics"].items():
        selector = os.getenv("GPU_ALLOCATION_" + vendor.upper() + "_" + name.upper() + "_PROMQL", default).strip()
        if selector.endswith("[5m]"):
            selector = selector[:-4]
        if not re.fullmatch(r"[a-zA-Z_:][a-zA-Z0-9_:]*(?:\{[^{}]*\})?", selector):
            raise ValueError("invalid_monitor_selector")
        queries[name] = f"{selector}[5m] @ {int(timestamp)}"
    return queries



def _scrape_interval(vendor="nvidia"):
    try:
        value = int(os.getenv("GPU_ALLOCATION_" + vendor.upper() + "_MONITOR_SCRAPE_INTERVAL_SECONDS", os.getenv("GPU_ALLOCATION_MONITOR_SCRAPE_INTERVAL_SECONDS", "30")))
        return value if 1 <= value <= 60 else 30
    except (TypeError, ValueError):
        return 30


def _coverage_fraction():
    try:
        value = float(os.getenv("GPU_ALLOCATION_MONITOR_COVERAGE_FRACTION", "0.8"))
        return value if math.isfinite(value) and 0.8 <= value <= 1 else 0.8
    except (TypeError, ValueError):
        return 0.8


def _monitor_values(rows, inventory, sampled_timestamp, query_name, vendor="nvidia"):
    values = {}
    raw_series = {}
    uuid_nodes = {}
    physical_aliases = {}
    physical_uuid_keys = {}
    ascend_ids = {}
    invalid = False
    scrape = _scrape_interval(vendor)
    expected_samples = math.ceil(300 / scrape)
    minimum_samples = max(2, math.ceil(expected_samples * _coverage_fraction()))
    valid_card_count = 0
    smallest_coverage = 1.0
    for row in rows or []:
        metric = row.get("metric") or {}
        node = next((str(metric.get(k) or "").strip() for k in (
            "node", "Hostname", "hostname", "kubernetes_node"
        ) if metric.get(k)), "")
        if node not in inventory:
            continue
        try:
            key, uuid = _identity(metric, node, vendor)
        except ValueError:
            invalid = True
            continue
        if vendor == "nvidia" and uuid in uuid_nodes and uuid_nodes[uuid] != node:
            invalid = True
        uuid_nodes[uuid] = node
        if uuid:
            if uuid in physical_uuid_keys and physical_uuid_keys[uuid] != key:
                invalid = True
            physical_uuid_keys[uuid] = key
        if vendor == "ascend" and metric.get("id") is not None:
            id_key = (node, str(metric["id"]))
            if id_key in ascend_ids and ascend_ids[id_key] != key:
                invalid = True
            ascend_ids[id_key] = key
        if key in physical_aliases and physical_aliases[key] != uuid:
            invalid = True
        physical_aliases[key] = uuid
        samples = {}
        series_invalid = False
        for pair in row.get("values") or []:
            try:
                timestamp, value = float(pair[0]), float(pair[1])
            except (TypeError, ValueError, IndexError, OverflowError):
                series_invalid = True
                continue
            if not math.isfinite(timestamp) or not math.isfinite(value):
                series_invalid = True
                continue
            if not sampled_timestamp - 300 < timestamp <= sampled_timestamp:
                series_invalid = True
                continue
            if value < 0 or query_name == "utilization" and value > 100:
                series_invalid = True
                continue
            if timestamp in samples and samples[timestamp] != value:
                series_invalid = True
            samples[timestamp] = value
        # Only ownership labels may split one physical exporter's stream.
        # Keep instance/job/exporter pod and all device metadata in the source
        # signature; never stitch different exporters into a complete window.
        signature = tuple(sorted(metric.items()))
        source = tuple((name, value) for name, value in signature if name not in BUSINESS_OWNER_LABELS)
        streams = raw_series.setdefault(key, {})
        fragments = streams.setdefault(source, {})
        if signature in fragments and fragments[signature] != samples:
            invalid = True
        fragments[signature] = samples
        if series_invalid or not samples:
            invalid = True

    merged_series = {}
    for key, streams in raw_series.items():
        source_samples = []
        for source, fragments in streams.items():
            source_labels = dict(source)
            if len(fragments) > 1 and not (source_labels.get("instance") and source_labels.get("job")):
                # Matching ownership labels without an exporter identity do not
                # prove that these fragments came from one scrape target.
                invalid = True
            samples = {}
            for fragment in fragments.values():
                for timestamp, value in fragment.items():
                    if timestamp in samples and samples[timestamp] != value:
                        invalid = True
                    samples[timestamp] = value
            source_samples.append(samples)
        # Identical replicas can be deduplicated, but different timestamps or
        # values remain a conflict even if their union would cover five minutes.
        if any(samples != source_samples[0] for samples in source_samples[1:]):
            invalid = True
        merged_series[key] = source_samples[0]

    # Fresh total-memory identities prove physical inventory independently of
    # utilization/window completeness. Sparse or stale monitoring still cannot
    # become a five-minute average. No instant evaluation timestamps are used.
    fresh_cards = {
        key for key, samples in merged_series.items()
        if samples and sampled_timestamp - max(samples) <= 2 * scrape
        and samples[max(samples)] > 0
    }
    inventory_valid = query_name == "memory_total" and not invalid and bool(sum(inventory.values())) and all(
        sum(node == name for node, _ in fresh_cards) == count
        for name, count in inventory.items()
    )
    for key, samples in merged_series.items():
        if not samples:
            continue
        ordered = sorted(samples.items())
        span = ordered[-1][0] - ordered[0][0]
        latest_age = sampled_timestamp - ordered[-1][0]
        max_gap = max((right[0] - left[0] for left, right in zip(ordered, ordered[1:])), default=300)
        coverage = min(len(samples) / expected_samples, (span + scrape) / 300, 1.0)
        smallest_coverage = min(smallest_coverage, coverage)
        temporal_valid = (
            len(samples) >= minimum_samples
            and span >= 300 - 2 * scrape
            and latest_age <= 2 * scrape and max_gap <= 2 * scrape
            and coverage >= _coverage_fraction()
        )
        if not temporal_valid:
            invalid = True
            continue
        valid_card_count += 1
        values[key] = {"average": sum(samples.values()) / len(samples),
                       "maximum": max(samples.values()), "coverage_fraction": coverage}
    complete = not invalid and all(
        sum(node == name for node, _ in values) == count
        for name, count in inventory.items()
    ) and bool(sum(inventory.values()))
    return values, complete, {"expected_cards": sum(inventory.values()),
                              "valid_cards": valid_card_count,
                              "minimum_temporal_coverage": round(smallest_coverage, 4) if raw_series else 0,
                              "expected_samples_per_card": expected_samples,
                              "minimum_samples_per_card": minimum_samples,
                              "physical_inventory_valid": inventory_valid}


def collect_monitor(client, inventory, diagnostics, sampled_timestamp, vendor="nvidia", *, include_observations=False):
    result = dict.fromkeys(("gpu_utilization_avg", "gpu_utilization_max",
                            "gpu_memory_utilization", "gpu_active_count"))
    values = {}
    complete = {}
    observation_rows, observation_errors = {}, []
    diagnostics["monitor_coverage"] = {}
    result["_memory_used_bytes"] = None
    result["_memory_total_bytes"] = None
    for name, query in _monitor_queries(sampled_timestamp, vendor).items():
        try:
            rows, error = client.query(query)
            if error:
                observation_errors.append(name)
                diagnostics["monitor_issues"].append(f"{name}_query_failed")
                values[name], complete[name] = {}, False
                continue
            observation_rows[name] = rows
            values[name], complete[name], coverage = _monitor_values(rows, inventory, sampled_timestamp, name, vendor)
            diagnostics["monitor_coverage"][name] = coverage
        except Exception:
            observation_errors.append(name)
            values[name], complete[name] = {}, False
        if not complete[name]:
            diagnostics["monitor_issues"].append(f"{name}_coverage_incomplete")
    if include_observations:
        from .gpu_monitor_observations import latest_observations
        result["observed_monitor"] = latest_observations(
            observation_rows, inventory, sampled_timestamp, vendor, observation_errors)
    average = values["utilization"]
    if all(complete.values()) and len({frozenset(items) for items in values.values()}) != 1:
        diagnostics["monitor_issues"].append("monitor_gpu_identity_mismatch")
        result["monitor_valid"] = False
        return result
    if complete["utilization"]:
        result["gpu_utilization_avg"] = round(sum(value["average"] for value in average.values()) / len(average), 4)
        result["gpu_utilization_max"] = round(max(value["maximum"] for value in average.values()), 4)
        try:
            threshold = float(os.getenv("GPU_ALLOCATION_ACTIVE_THRESHOLD_PERCENT", "5"))
            if not math.isfinite(threshold) or not 0 < threshold <= 100:
                threshold = 5
        except (TypeError, ValueError):
            threshold = 5
        result["gpu_active_count"] = sum(value["average"] >= threshold for value in average.values())
    used, total = values["memory_used"], values["memory_total"]
    if complete["memory_used"] and complete["memory_total"] and set(used) == set(total):
        if all(total[key]["average"] > 0 and 0 <= used[key]["average"] <= total[key]["average"] for key in total):
            result["gpu_memory_utilization"] = round(
                100 * sum(value["average"] for value in used.values())
                / sum(value["average"] for value in total.values()), 4)
    multiplier = _memory_multiplier(vendor)
    if result["gpu_memory_utilization"] is not None and multiplier is not None:
        result["_memory_used_bytes"] = sum(value["average"] for value in used.values()) * multiplier
        result["_memory_total_bytes"] = sum(value["average"] for value in total.values()) * multiplier
    elif multiplier is None:
        result["gpu_memory_utilization"] = None
        diagnostics["monitor_issues"].append("memory_unit_invalid")

    if result["gpu_utilization_avg"] is None:
        diagnostics["monitor_issues"].append("gpu_utilization_unavailable")
    if result["gpu_memory_utilization"] is None:
        diagnostics["monitor_issues"].append("gpu_memory_utilization_unavailable")
    result["monitor_valid"] = all(result[name] is not None for name in (
        "gpu_utilization_avg", "gpu_utilization_max", "gpu_memory_utilization"
    ))
    return result
