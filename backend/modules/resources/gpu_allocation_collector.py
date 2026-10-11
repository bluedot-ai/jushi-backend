"""Physical NVIDIA/Ascend allocation snapshots, independent of page requests.

Only Kubernetes resources proven to represent whole physical GPUs are accepted.
Ambiguous inventory and incomplete monitoring are recorded as missing, never 0.
"""

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

try:
    from backend.config import Config
    from backend.services.k8s_client import K8sClient
    from backend.services.prometheus_client import PrometheusClient
except ModuleNotFoundError:
    from config import Config
    from services.k8s_client import K8sClient
    from services.prometheus_client import PrometheusClient

from .gpu_allocation_repository import cleanup_snapshots, save_snapshot
from . import gpu_allocation_providers as providers


# Modern China has no DST. Fixed UTC+08 avoids adding tzdata to offline images.
LOCAL_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
CALCULATION_VERSION = "physical-accelerator-v2"
_logger = logging.getLogger(__name__)
_collector_lock = threading.Lock()
_collection_lock = threading.Lock()
_collector_thread = None
_collector_started = False


def _enabled(name, default=True):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _interval_seconds():
    try:
        return max(60, int(os.getenv("GPU_ALLOCATION_INTERVAL_SECONDS", "300")))
    except (TypeError, ValueError):
        return 300


def _local_now(now=None):
    if now is None:
        return datetime.now(LOCAL_TIMEZONE).replace(tzinfo=None)
    if now.tzinfo is not None:
        return now.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None)
    return now


def retention_cutoff(now=None):
    """Scheme B: current month plus six complete preceding local months."""
    current = _local_now(now)
    month_index = current.year * 12 + current.month - 1 - 6
    year, month = divmod(month_index, 12)
    return datetime(year, month + 1, 1)


def _gpu_quantity(raw):
    try:
        number = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid physical GPU quantity") from None
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        raise ValueError("invalid physical GPU quantity")
    return int(number)


def _container_request(container, resource_key):
    resources = container.get("resources") or {}
    requests = resources.get("requests") or {}
    limits = resources.get("limits") or {}
    return _gpu_quantity(requests.get(resource_key, limits.get(resource_key, 0)))


def effective_pod_request(pod, resource_key="nvidia.com/gpu"):
    """Match scheduler effective requests, including restartable init sidecars."""
    spec = pod.get("spec") or {}
    regular = sum(_container_request(c, resource_key) for c in spec.get("containers") or [])
    sidecars = 0
    init_peak = 0
    for container in spec.get("initContainers") or []:
        request = _container_request(container, resource_key)
        if container.get("restartPolicy") == "Always":
            sidecars += request
            init_peak = max(init_peak, sidecars)
        else:
            init_peak = max(init_peak, sidecars + request)
    overhead = _gpu_quantity((spec.get("overhead") or {}).get(resource_key, 0))
    return max(regular + sidecars, init_peak) + overhead


def _virtual_inventory(node, resource_key, capacity):
    labels = (node.get("metadata") or {}).get("labels") or {}
    status = node.get("status") or {}
    resource_names = set(status.get("capacity") or {}) | set(status.get("allocatable") or {})
    if resource_key.startswith("huawei.com/Ascend"):
        virtual_keys = [key for key in resource_names if key.startswith("huawei.com/Ascend") and (
            "-" in key.split("/", 1)[1] or "memory" in key.lower() or "core" in key.lower()
        )]
        for key in virtual_keys:
            try:
                # Device plugins may publish unused partition aliases as zero.
                # Ignore only verified zeros in BOTH resource maps.
                if any(_gpu_quantity((status.get(field) or {}).get(key, 0)) > 0
                       for field in ("capacity", "allocatable")):
                    return "virtual_ascend_resources_present"
            except ValueError:
                return "ascend_virtual_resource_quantity_invalid"
        if any(str(value).lower() not in ("", "none", "false", "0")
               for key, value in labels.items() if key.startswith("huawei.com/")
               and any(marker in key.lower() for marker in ("vnpu", "sharing", "split"))):
            return "ascend_sharing_enabled"
        return None
    if resource_key != "nvidia.com/gpu":
        return "unverified_physical_resource_key"
    sharing = str(labels.get("nvidia.com/gpu.sharing-strategy", "none")).lower()
    if sharing not in ("", "none"):
        return "gpu_sharing_enabled"
    try:
        if _gpu_quantity(labels.get("nvidia.com/gpu.replicas", 1)) > 1:
            return "gpu_replicas_enabled"
    except ValueError:
        return "gpu_replicas_invalid"
    if "SHARED" in str(labels.get("nvidia.com/gpu.product", "")).upper():
        return "shared_gpu_product"
    if str(labels.get("nvidia.com/mig.strategy", "none")).lower() not in ("", "none"):
        return "mig_enabled"
    if any(key.startswith("nvidia.com/mig-") or key in (
        "nvidia.com/gpucores", "nvidia.com/gpumem", "nvidia.com/gpumem-percentage",
        "nvidia.com/vgpu", "nvidia.com/gpu.shared",
    ) for key in resource_names):
        return "virtual_gpu_resources_present"
    physical_count = labels.get("nvidia.com/gpu.count")
    if physical_count is not None:
        try:
            if _gpu_quantity(physical_count) != capacity:
                return "gpu_inventory_count_mismatch"
        except ValueError:
            return "gpu_inventory_count_invalid"
    return None


def _list_items(result, kind):
    status_code, payload = result
    if status_code != 200 or not isinstance(payload, dict):
        raise ValueError(f"{kind}_unavailable")
    # The shared K8s client does not expose continuation parameters. Never
    # publish a total from a partial page or spin through unlimited requests.
    if (payload.get("metadata") or {}).get("continue"):
        raise ValueError(f"{kind}_incomplete_page")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError(f"{kind}_invalid_response")
    return items


def _allocation(k8s, resource_key, diagnostics, *, nodes=None, pods=None, vendor="nvidia"):
    keys = (resource_key,) if isinstance(resource_key, str) else tuple(resource_key)
    if vendor == "nvidia" and keys != ("nvidia.com/gpu",):
        diagnostics["allocation_issues"] = ["unverified_physical_resource_key"]
        return None, None, None, {}, False
    nodes = nodes if nodes is not None else _list_items(k8s.list_nodes(), "nodes")
    pods = pods if pods is not None else _list_items(k8s.list_cluster_pods(), "pods")
    capacity_by_node = {}
    schedulable = {}
    node_resource_keys = {}
    issues = []
    for node in nodes:
        name = str((node.get("metadata") or {}).get("name") or "")
        status = node.get("status") or {}
        capacities = status.get("capacity") or {}
        allocatables = status.get("allocatable") or {}
        present_keys = [key for key in keys if key in capacities or key in allocatables]
        if not present_keys:
            if vendor == "ascend" and any(key.startswith("huawei.com/Ascend") for key in set(capacities) | set(allocatables)):
                issues.append("ascend_resource_key_not_configured")
            continue
        if len(present_keys) > 1:
            issues.append("ambiguous_device_resource_aliases")
            continue
        resource_key = present_keys[0]
        if not name or name in capacity_by_node:
            issues.append("invalid_or_duplicate_gpu_node")
            continue
        try:
            capacity = _gpu_quantity(capacities.get(resource_key))
            allocatable = _gpu_quantity(allocatables.get(resource_key))
        except ValueError:
            issues.append("gpu_node_quantity_invalid")
            continue
        ambiguity = _virtual_inventory(node, resource_key, capacity)
        if ambiguity:
            issues.append(ambiguity)
        if allocatable > capacity:
            issues.append("gpu_allocatable_exceeds_capacity")
        capacity_by_node[name] = capacity
        node_resource_keys[name] = resource_key
        ready = any(c.get("type") == "Ready" and c.get("status") == "True"
                    for c in status.get("conditions") or [])
        if ready and not (node.get("spec") or {}).get("unschedulable"):
            schedulable[name] = allocatable

    allocation_by_node = {name: 0 for name in schedulable}
    seen_pods = set()
    for pod in pods:
        spec = pod.get("spec") or {}
        node_name = spec.get("nodeName")
        if node_name not in schedulable:
            continue
        if (pod.get("status") or {}).get("phase") in ("Succeeded", "Failed"):
            continue
        metadata = pod.get("metadata") or {}
        identity = metadata.get("uid") or (
            metadata.get("namespace", "default"), metadata.get("name")
        )
        if identity in seen_pods:
            issues.append("duplicate_pod_identity")
            continue
        seen_pods.add(identity)
        try:
            allocation_by_node[node_name] += effective_pod_request(pod, node_resource_keys[node_name])
        except (ValueError, TypeError):
            issues.append("pod_gpu_quantity_invalid")
    if any(allocation_by_node[name] > schedulable[name] for name in schedulable):
        issues.append("gpu_allocation_exceeds_allocatable")
    diagnostics["allocation_issues"] = sorted(set(issues))
    diagnostics["managed_gpu_nodes"] = len(capacity_by_node)
    diagnostics["schedulable_gpu_nodes"] = len(schedulable)
    if issues and set(issues) != {"gpu_inventory_count_mismatch"}:
        return None, None, None, {}, False
    return (sum(capacity_by_node.values()), sum(schedulable.values()),
            sum(allocation_by_node.values()), capacity_by_node, not issues)


def _scrape_interval(vendor="nvidia"):
    return providers._scrape_interval(vendor)


def _monitor(client, inventory, diagnostics, sampled_timestamp, vendor="nvidia", *, include_observations=False):
    return providers.collect_monitor(client, inventory, diagnostics, sampled_timestamp, vendor,
                                     include_observations=include_observations)


def _empty_snapshot(now, vendor):
    sampled_at = _local_now(now).replace(microsecond=0)
    interval = _interval_seconds()
    timestamp = sampled_at.replace(tzinfo=LOCAL_TIMEZONE).timestamp()
    slot = datetime.fromtimestamp(timestamp - timestamp % interval, LOCAL_TIMEZONE).replace(tzinfo=None)
    return {
        "sampled_at": sampled_at, "sample_slot": slot, "cluster_name": os.getenv(
            "GPU_ALLOCATION_CLUSTER_NAME", getattr(Config, "DCE_CLUSTER", "default")) or "default",
        "vendor": vendor, "gpu_capacity": None, "gpu_allocatable": None, "gpu_allocated": None,
        "allocation_rate": None, "gpu_utilization_avg": None, "gpu_utilization_max": None,
        "gpu_memory_utilization": None, "gpu_active_count": None,
        "allocation_source": "kubernetes", "monitor_source": providers.PROVIDERS[vendor]["monitor_source"] if vendor != "all" else "prometheus-physical-accelerators",
        "allocation_valid": False, "monitor_valid": False,
        "calculation_version": CALCULATION_VERSION, "sample_interval_seconds": interval,
    }


def _vendor_snapshot(now, vendor, k8s, nodes, pods, source_error=None, *, include_observations=False):
    snapshot = _empty_snapshot(now, vendor)
    diagnostics = {
        "allocation_issues": [], "allocation_warnings": [], "monitor_issues": [],
        "monitor_scope": "all_managed_physical_" + vendor + "_nodes_including_notready",
        "monitor_window_seconds": 300, "monitor_scrape_interval_seconds": _scrape_interval(vendor),
    }
    inventory = {}
    capacity = allocatable = allocated = None
    try:
        if source_error:
            raise ValueError(source_error)
        capacity, allocatable, allocated, inventory, valid = _allocation(
            k8s, providers.resource_keys(vendor), diagnostics,
            nodes=nodes, pods=pods, vendor=vendor,
        )
        snapshot.update(gpu_capacity=capacity if valid else None,
                        gpu_allocatable=allocatable if valid else None,
                        gpu_allocated=allocated if valid else None, allocation_valid=valid)
        if valid and allocatable:
            snapshot["allocation_rate"] = round(100 * allocated / allocatable, 4)
    except Exception as exc:
        safe_errors = {
            "kubernetes_credentials_missing", "nodes_unavailable", "pods_unavailable",
            "nodes_incomplete_page", "pods_incomplete_page", "nodes_invalid_response",
            "pods_invalid_response", "unverified_ascend_resource_key",
        }
        reason = str(exc) if isinstance(exc, ValueError) and str(exc) in safe_errors else "allocation_collection_failed"
        diagnostics["allocation_issues"].append(reason)
    if inventory and sum(inventory.values()) and _enabled("PROMETHEUS_GPU_USAGE_ENABLED"):
        try:
            timestamp = snapshot["sampled_at"].replace(tzinfo=LOCAL_TIMEZONE).timestamp()
            snapshot.update(_monitor(PrometheusClient.from_config(Config), inventory, diagnostics, timestamp, vendor,
                                     include_observations=include_observations))
        except Exception:
            diagnostics["monitor_issues"].append("monitor_collection_failed")
        inventory_verified = diagnostics.get("monitor_coverage", {}).get("memory_total", {}).get("physical_inventory_valid", False)
        if diagnostics["allocation_issues"] == ["gpu_inventory_count_mismatch"] and inventory_verified:
            diagnostics["allocation_issues"] = []
            diagnostics["allocation_warnings"].append("stale_gpu_count_label_reconciled_by_dcgm")
            snapshot.update(gpu_capacity=capacity, gpu_allocatable=allocatable,
                            gpu_allocated=allocated, allocation_valid=True,
                            allocation_rate=round(100 * allocated / allocatable, 4) if allocatable else None)
    else:
        diagnostics["monitor_issues"].append("monitoring_disabled_or_inventory_unavailable")
    if include_observations and "observed_monitor" not in snapshot:
        from .gpu_monitor_observations import latest_observations
        timestamp = snapshot["sampled_at"].replace(tzinfo=LOCAL_TIMEZONE).timestamp()
        snapshot["observed_monitor"] = latest_observations({}, inventory, timestamp, vendor,
                                                        known=capacity is not None)
    return snapshot, diagnostics


def _all_snapshot(now, vendor_snapshots):
    result = _empty_snapshot(now, "all")
    if all(row["allocation_valid"] for row in vendor_snapshots):
        for field in ("gpu_capacity", "gpu_allocatable", "gpu_allocated"):
            result[field] = sum(row[field] for row in vendor_snapshots)
        result["allocation_valid"] = True
        if result["gpu_allocatable"]:
            result["allocation_rate"] = round(100 * result["gpu_allocated"] / result["gpu_allocatable"], 4)
    # Unknown inventory cannot be excluded as if that vendor had zero cards.
    present = [row for row in vendor_snapshots if row["gpu_capacity"] is None or row["gpu_capacity"] > 0]
    if present and all(row["gpu_capacity"] is not None and row["gpu_utilization_avg"] is not None for row in present):
        cards = sum(row["gpu_capacity"] for row in present)
        result["gpu_utilization_avg"] = round(sum(row["gpu_utilization_avg"] * row["gpu_capacity"] for row in present) / cards, 4)
        if all(row["gpu_utilization_max"] is not None for row in present):
            result["gpu_utilization_max"] = max(row["gpu_utilization_max"] for row in present)
        if all(row["gpu_active_count"] is not None for row in present):
            result["gpu_active_count"] = sum(row["gpu_active_count"] for row in present)
    if present and all(row.get("_memory_used_bytes") is not None and row.get("_memory_total_bytes") is not None and row["_memory_total_bytes"] > 0 for row in present):
        result["gpu_memory_utilization"] = round(
            100 * sum(row["_memory_used_bytes"] for row in present)
            / sum(row["_memory_total_bytes"] for row in present), 4)
    result["monitor_valid"] = all(result[field] is not None for field in (
        "gpu_utilization_avg", "gpu_utilization_max", "gpu_memory_utilization"))
    return result


def build_current_snapshot(now=None, vendor="all", *, include_observations=False):
    """Read the node/pod lists once, then form independent physical-vendor scopes."""
    if vendor not in ("all", "nvidia", "ascend"):
        raise ValueError("vendor must be all, nvidia or ascend")
    now = _local_now(now).replace(microsecond=0)
    source_error = None
    nodes, pods, k8s = [], [], None
    try:
        k8s = K8sClient.from_config(Config)
        if not k8s.api_base or not k8s.token:
            raise ValueError("kubernetes_credentials_missing")
        nodes = _list_items(k8s.list_nodes(), "nodes")
        pods = _list_items(k8s.list_cluster_pods(), "pods")
    except Exception as exc:
        safe = {"kubernetes_credentials_missing", "nodes_unavailable", "pods_unavailable",
                "nodes_incomplete_page", "pods_incomplete_page", "nodes_invalid_response", "pods_invalid_response"}
        source_error = str(exc) if isinstance(exc, ValueError) and str(exc) in safe else "allocation_collection_failed"
    entries, by_vendor = [], {}
    for scope in ("nvidia", "ascend"):
        row, diagnostic = _vendor_snapshot(now, scope, k8s, nodes, pods, source_error,
                                          include_observations=include_observations)
        entries.append(row)
        by_vendor[scope] = diagnostic
    aggregate = _all_snapshot(now, entries)
    if include_observations:
        from .gpu_monitor_observations import combine_observations, public_observations
        aggregate["observed_monitor"] = public_observations(combine_observations(
            [row["observed_monitor"] for row in entries]))
        for row in entries:
            row["observed_monitor"] = public_observations(row["observed_monitor"])
    # Internal byte counts are only for correct cross-vendor capacity weighting.
    for row in entries:
        row.pop("_memory_used_bytes", None)
        row.pop("_memory_total_bytes", None)
    selected = aggregate if vendor == "all" else next(row.copy() for row in entries if row["vendor"] == vendor)
    selected["vendors"] = entries
    if vendor == "all":
        diagnostics = {
            "vendors": by_vendor,
            "allocation_issues": [scope + ":" + issue for scope, diag in by_vendor.items() for issue in diag["allocation_issues"]],
            "allocation_warnings": [scope + ":" + issue for scope, diag in by_vendor.items() for issue in diag["allocation_warnings"]],
            "monitor_issues": [scope + ":" + issue for scope, diag in by_vendor.items() for issue in diag["monitor_issues"]],
            "monitor_window_seconds": 300,
            "monitor_scope": "all_managed_physical_nvidia_and_ascend_nodes_including_notready",
        }
    else:
        diagnostics = by_vendor[vendor]
    return selected, diagnostics


def collect_and_save_once(now=None):
    """Persist all/NVIDIA/Ascend scopes without letting one failed write stop others."""
    with _collection_lock:
        snapshot, diagnostics = build_current_snapshot(now)
        rows = [{key: value for key, value in snapshot.items() if key != "vendors"}] + snapshot.get("vendors", [])
        saved_vendors, errors = [], []
        for row in rows:
            try:
                error = save_snapshot(row)
            except Exception:
                error = "snapshot_write_failed"
            if error:
                errors.append(row.get("vendor", "all"))
            else:
                saved_vendors.append(row.get("vendor", "all"))
    return {"snapshot": snapshot, "diagnostics": diagnostics, "saved": not errors,
            "saved_vendors": saved_vendors, "save_error": "snapshot_write_failed" if errors else None}


def _collector_loop():
    next_run = time.monotonic()
    next_cleanup = next_run
    while True:
        try:
            result = collect_and_save_once()
            if not result["saved"]:
                _logger.warning("GPU allocation snapshot write failed")
        except Exception as exc:
            _logger.error("GPU allocation collection failed (%s); will retry", type(exc).__name__)
        current = time.monotonic()
        if current >= next_cleanup:
            try:
                _, error = cleanup_snapshots(retention_cutoff())
                if error:
                    _logger.warning("GPU allocation retention cleanup failed")
            except Exception as exc:
                _logger.error("GPU allocation cleanup failed (%s); will retry", type(exc).__name__)
            next_cleanup = current + 3600
        next_run += _interval_seconds()
        if next_run <= time.monotonic():
            next_run = time.monotonic() + _interval_seconds()
        time.sleep(max(next_run - time.monotonic(), 1))


def start_gpu_allocation_collector():
    """Start once per process, but permit restart if a previous thread died."""
    global _collector_thread, _collector_started
    if not _enabled("GPU_ALLOCATION_HISTORY_ENABLED"):
        return False
    with _collector_lock:
        if _collector_thread is not None and _collector_thread.is_alive():
            return False
        _collector_started = False
        _collector_thread = threading.Thread(
            target=_collector_worker, name="jushi-gpu-allocation-collector", daemon=True,
        )
        _collector_thread.start()
        _collector_started = _collector_thread.is_alive()
        return _collector_started


def _collector_worker():
    global _collector_started
    try:
        _collector_loop()
    finally:
        with _collector_lock:
            if _collector_thread is threading.current_thread():
                _collector_started = False
