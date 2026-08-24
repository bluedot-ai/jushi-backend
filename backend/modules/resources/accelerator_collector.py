"""Background collection of Prometheus per-card memory metrics into MySQL."""

import math
import threading
import time
from datetime import datetime

try:
    from backend.config import Config
    from backend.services.prometheus_client import PrometheusClient
except ModuleNotFoundError:
    from config import Config
    from services.prometheus_client import PrometheusClient

from .accelerator_repository import (
    cleanup_accelerator_samples,
    latest_accelerator_sample_time,
    save_accelerator_samples,
)
from .settings import (
    _accelerator_history_backfill_seconds,
    _accelerator_history_cluster_name,
    _accelerator_history_enabled,
    _accelerator_history_interval_seconds,
    _accelerator_history_retention_days,
    _prometheus_gpu_usage_enabled,
)


NVIDIA_LABELS = "node, Hostname, UUID, gpu, device, modelName"
ASCEND_LABELS = "node, Hostname, id, vdie_id, model_name, pcie_bus_info"
MEMORY_QUERIES = {
    "nvidia_total": (
        "nvidia",
        "total",
        f"max by ({NVIDIA_LABELS}) "
        '(DCGM_FI_DEV_FB_TOTAL{job="nvidia-dcgm-exporter"})',
    ),
    "nvidia_used": (
        "nvidia",
        "used",
        f"max by ({NVIDIA_LABELS}) "
        '(DCGM_FI_DEV_FB_USED{job="nvidia-dcgm-exporter"})',
    ),
    "ascend_total": (
        "ascend",
        "total",
        f"max by ({ASCEND_LABELS}) "
        '(npu_chip_info_total_memory{job="npu-exporter"})',
    ),
    "ascend_used": (
        "ascend",
        "used",
        f"max by ({ASCEND_LABELS}) "
        '(npu_chip_info_used_memory{job="npu-exporter"})',
    ),
}

_collector_lock = threading.Lock()
_collector_started = False


def _finite_float(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _node_name(metric):
    for key in ("node", "Hostname", "hostname", "kubernetes_node"):
        value = str(metric.get(key) or "").strip()
        if value:
            return value
    return ""


def _card_id(metric, vendor):
    key = "UUID" if vendor == "nvidia" else "vdie_id"
    return str(metric.get(key) or "").strip()


def _device_index(metric, vendor):
    raw = metric.get("gpu") if vendor == "nvidia" else metric.get("id")
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _metadata(metric, vendor):
    device_name = (
        metric.get("device")
        if vendor == "nvidia"
        else metric.get("pcie_bus_info")
    )
    model_name = (
        metric.get("modelName")
        if vendor == "nvidia"
        else metric.get("model_name")
    )
    return {
        "node_name": _node_name(metric),
        "card_id": _card_id(metric, vendor),
        "device_index": _device_index(metric, vendor),
        "device_name": str(device_name or "").strip(),
        "model_name": str(model_name or "Unknown").strip(),
    }


def _instant_value(row):
    raw = row.get("value") or []
    return _finite_float(raw[1]) if len(raw) >= 2 else None


def _aligned_timestamp(raw_timestamp, interval_seconds):
    raw = int(float(raw_timestamp))
    return raw - (raw % max(int(interval_seconds), 1))


def _merge_value(samples, metric, vendor, value_kind, sampled_timestamp, value):
    metadata = _metadata(metric, vendor)
    if not metadata["node_name"] or not metadata["card_id"]:
        return False

    key = (
        vendor,
        metadata["node_name"],
        metadata["card_id"],
        sampled_timestamp,
    )
    sample = samples.setdefault(key, {
        **metadata,
        "vendor": vendor,
        "sampled_timestamp": sampled_timestamp,
        "memory_used_mib": None,
        "memory_total_mib": None,
    })
    for field in ("device_index", "device_name", "model_name"):
        if metadata.get(field) not in (None, ""):
            sample[field] = metadata[field]
    sample[f"memory_{value_kind}_mib"] = max(value, 0) if value is not None else None
    return True


def _finalize_samples(samples, cluster_name):
    result = []
    for sample in samples.values():
        used = sample.get("memory_used_mib")
        total = sample.get("memory_total_mib")
        if used is not None and total is not None and total > 0:
            used = min(used, total)
            utilization = min(max(100 * used / total, 0), 100)
        else:
            utilization = None

        result.append({
            "sampled_at": datetime.fromtimestamp(sample["sampled_timestamp"]),
            "cluster_name": cluster_name,
            "node_name": sample["node_name"],
            "vendor": sample["vendor"],
            "card_id": sample["card_id"],
            "device_index": sample.get("device_index"),
            "device_name": sample.get("device_name") or "",
            "model_name": sample.get("model_name") or "Unknown",
            "memory_used_mib": round(used, 3) if used is not None else None,
            "memory_total_mib": round(total, 3) if total is not None else None,
            "memory_utilization_percent": (
                round(utilization, 3) if utilization is not None else None
            ),
            "metric_source": "prometheus",
        })
    result.sort(key=lambda item: (
        item["sampled_at"],
        item["node_name"],
        item["vendor"],
        item["device_index"] if item["device_index"] is not None else 10 ** 9,
        item["card_id"],
    ))
    return result


def collect_accelerator_samples(
    client,
    *,
    start_timestamp=None,
    end_timestamp=None,
    interval_seconds=None,
    cluster_name=None,
):
    interval = interval_seconds or _accelerator_history_interval_seconds()
    cluster = cluster_name or _accelerator_history_cluster_name()
    range_query = start_timestamp is not None and end_timestamp is not None
    samples = {}
    failed_queries = []
    skipped_identity_rows = 0

    for query_name, (vendor, value_kind, promql) in MEMORY_QUERIES.items():
        if range_query:
            rows, error = client.query_range(
                promql,
                int(start_timestamp),
                int(end_timestamp),
                interval,
            )
        else:
            rows, error = client.query(promql)
        if error:
            failed_queries.append(query_name)
            continue

        for row in rows or []:
            metric = row.get("metric") or {}
            if range_query:
                raw_values = row.get("values") or []
                values = [
                    (
                        _aligned_timestamp(raw_timestamp, interval),
                        _finite_float(raw_value),
                    )
                    for raw_timestamp, raw_value in raw_values
                ]
            else:
                now_timestamp = int(end_timestamp or time.time())
                values = [
                    (_aligned_timestamp(now_timestamp, interval), _instant_value(row))
                ]

            for sampled_timestamp, value in values:
                if value is None:
                    continue
                if not _merge_value(
                    samples,
                    metric,
                    vendor,
                    value_kind,
                    sampled_timestamp,
                    value,
                ):
                    skipped_identity_rows += 1

    return _finalize_samples(samples, cluster), {
        "failed_queries": failed_queries,
        "skipped_identity_rows": skipped_identity_rows,
    }


def collect_and_save_once(client=None, now_timestamp=None):
    current_client = client or PrometheusClient.from_config(Config)
    samples, diagnostics = collect_accelerator_samples(
        current_client,
        end_timestamp=int(now_timestamp or time.time()),
    )
    saved_count, save_error = save_accelerator_samples(samples)
    return {
        "sample_count": len(samples),
        "saved_count": saved_count,
        "save_error": save_error,
        **diagnostics,
    }


def _backfill_recent_history(client):
    backfill_seconds = _accelerator_history_backfill_seconds()
    if backfill_seconds <= 0:
        return

    interval = _accelerator_history_interval_seconds()
    cluster = _accelerator_history_cluster_name()
    end_timestamp = _aligned_timestamp(time.time(), interval)
    latest, latest_error = latest_accelerator_sample_time(cluster)
    earliest_timestamp = end_timestamp - backfill_seconds
    if latest_error:
        print(f"[Jushi] Accelerator history: latest sample lookup failed: {latest_error}")
    elif isinstance(latest, datetime):
        earliest_timestamp = max(
            earliest_timestamp,
            int(latest.timestamp()) + interval,
        )
    if earliest_timestamp >= end_timestamp:
        return

    samples, diagnostics = collect_accelerator_samples(
        client,
        start_timestamp=earliest_timestamp,
        end_timestamp=end_timestamp,
        interval_seconds=interval,
        cluster_name=cluster,
    )
    saved_count, error = save_accelerator_samples(samples)
    if error:
        print(f"[Jushi] Accelerator history: backfill failed: {error}")
        return
    print(
        "[Jushi] Accelerator history: backfill completed "
        f"samples={saved_count} failed_queries={diagnostics['failed_queries']} "
        f"skipped_identity_rows={diagnostics['skipped_identity_rows']}"
    )


def _collector_loop():
    client = PrometheusClient.from_config(Config)
    _backfill_recent_history(client)
    last_cleanup_at = 0

    while True:
        started_at = time.time()
        result = collect_and_save_once(client, now_timestamp=started_at)
        if result["save_error"]:
            print(
                "[Jushi] Accelerator history: collection save failed "
                f"error={result['save_error']}"
            )
        else:
            print(
                "[Jushi] Accelerator history: collection completed "
                f"samples={result['saved_count']} "
                f"failed_queries={result['failed_queries']} "
                f"skipped_identity_rows={result['skipped_identity_rows']}"
            )

        if started_at - last_cleanup_at >= 60 * 60:
            deleted, cleanup_error = cleanup_accelerator_samples(
                _accelerator_history_retention_days()
            )
            if cleanup_error:
                print(
                    "[Jushi] Accelerator history: cleanup failed "
                    f"error={cleanup_error}"
                )
            elif deleted:
                print(
                    "[Jushi] Accelerator history: cleanup completed "
                    f"deleted={deleted}"
                )
            last_cleanup_at = started_at

        elapsed = time.time() - started_at
        time.sleep(max(_accelerator_history_interval_seconds() - elapsed, 1))


def start_accelerator_metric_collector():
    global _collector_started

    if (
        not _accelerator_history_enabled()
        or not _prometheus_gpu_usage_enabled()
        or not str(getattr(Config, "PROMETHEUS_BASE_URL", "") or "").strip()
    ):
        return False

    with _collector_lock:
        if _collector_started:
            return False
        thread = threading.Thread(
            target=_collector_loop,
            name="jushi-accelerator-history-collector",
            daemon=True,
        )
        thread.start()
        _collector_started = True
        return True

