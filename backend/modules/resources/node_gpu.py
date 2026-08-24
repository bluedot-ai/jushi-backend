"""Prometheus-backed realtime details and MySQL-backed per-card trends."""

import math
import re
import time
from datetime import datetime

try:
    from backend.config import Config
    from backend.services.prometheus_client import PrometheusClient
except ModuleNotFoundError:
    from config import Config
    from services.prometheus_client import PrometheusClient

from .accelerator_repository import load_accelerator_trend_buckets
from .response import _error, _ok
from .settings import (
    _accelerator_history_cluster_name,
    _prometheus_gpu_usage_enabled,
)


NODE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,251}[A-Za-z0-9])?$")
TREND_RANGES = {
    "1h": {"seconds": 60 * 60, "step": 60},
    "24h": {"seconds": 24 * 60 * 60, "step": 15 * 60},
    "7d": {"seconds": 7 * 24 * 60 * 60, "step": 60 * 60},
}
TREND_METRICS = {"memory_utilization"}


NVIDIA_LABELS = "node, UUID, gpu, device, modelName"
ASCEND_LABELS = "node, id, vdie_id, model_name, pcie_bus_info"


def validate_node_name(node_name):
    value = str(node_name or "").strip()
    if not value or not NODE_NAME_PATTERN.fullmatch(value):
        return "", "Invalid node name"
    return value, None


def _client():
    if not _prometheus_gpu_usage_enabled():
        return None, "Prometheus GPU metrics are disabled"
    client = PrometheusClient.from_config(Config)
    if not client.base_url:
        return None, "PROMETHEUS_BASE_URL is not configured"
    return client, None


def _instant_queries(node_name):
    selector = f'node="{node_name}"'
    return {
        "nvidia_total": (
            "nvidia",
            f"max by ({NVIDIA_LABELS}) "
            f'(DCGM_FI_DEV_FB_TOTAL{{job="nvidia-dcgm-exporter",{selector}}})',
        ),
        "nvidia_used": (
            "nvidia",
            f"max by ({NVIDIA_LABELS}) "
            f'(DCGM_FI_DEV_FB_USED{{job="nvidia-dcgm-exporter",{selector}}})',
        ),
        "nvidia_util": (
            "nvidia",
            f"max by ({NVIDIA_LABELS}) "
            f'(DCGM_FI_DEV_GPU_UTIL{{job="nvidia-dcgm-exporter",{selector}}})',
        ),
        "ascend_total": (
            "ascend",
            f"max by ({ASCEND_LABELS}) "
            f'(npu_chip_info_total_memory{{job="npu-exporter",{selector}}})',
        ),
        "ascend_used": (
            "ascend",
            f"max by ({ASCEND_LABELS}) "
            f'(npu_chip_info_used_memory{{job="npu-exporter",{selector}}})',
        ),
        "ascend_util": (
            "ascend",
            f"max by ({ASCEND_LABELS}) "
            f'(npu_chip_info_utilization{{job="npu-exporter",{selector}}})',
        ),
    }


def _float_value(raw, default=None):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _row_value(row):
    value = row.get("value") or []
    if len(value) < 2:
        return None
    return _float_value(value[1])


def _card_identity(metric, vendor):
    if vendor == "nvidia":
        return str(metric.get("UUID") or metric.get("device") or "").strip()
    return str(metric.get("vdie_id") or metric.get("pcie_bus_info") or "").strip()


def _card_index(metric, vendor):
    raw = metric.get("gpu") if vendor == "nvidia" else metric.get("id")
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 10 ** 9


def _card_model(metric, vendor):
    key = "modelName" if vendor == "nvidia" else "model_name"
    return str(metric.get(key) or "Unknown").strip()


def _display_name(sequence_index):
    return f"GPU {sequence_index + 1}"


def _health_level(gpu_percent, memory_percent):
    value = max(gpu_percent or 0, memory_percent or 0)
    if value >= 90:
        return "red"
    if value >= 70:
        return "yellow"
    return "green"


def _build_realtime_cards(results):
    cards = {}

    for query_key in ("nvidia_total", "ascend_total"):
        vendor, rows = results.get(query_key, ("", []))
        for row in rows or []:
            metric = row.get("metric") or {}
            card_id = _card_identity(metric, vendor)
            if not card_id:
                continue
            cards[card_id] = {
                "card_id": card_id,
                "vendor": vendor,
                "device_index": _card_index(metric, vendor),
                "device": metric.get("device") or metric.get("pcie_bus_info") or "",
                "model": _card_model(metric, vendor),
                "memory_total_mib": max(_row_value(row) or 0, 0),
                "memory_used_mib": None,
                "memory_utilization_percent": None,
                "gpu_utilization_percent": None,
            }

    for query_key, value_key in (
        ("nvidia_used", "memory_used_mib"),
        ("ascend_used", "memory_used_mib"),
        ("nvidia_util", "gpu_utilization_percent"),
        ("ascend_util", "gpu_utilization_percent"),
    ):
        vendor, rows = results.get(query_key, ("", []))
        for row in rows or []:
            metric = row.get("metric") or {}
            card_id = _card_identity(metric, vendor)
            value = _row_value(row)
            if card_id not in cards or value is None:
                continue
            cards[card_id][value_key] = max(value, 0)

    ordered = sorted(
        cards.values(),
        key=lambda card: (card["vendor"], card["device_index"], card["card_id"]),
    )
    for display_index, card in enumerate(ordered):
        total = card["memory_total_mib"]
        raw_used = card["memory_used_mib"]
        used = min(raw_used, total) if raw_used is not None and total > 0 else raw_used
        memory_percent = 100 * used / total if used is not None and total > 0 else None
        gpu_percent = card["gpu_utilization_percent"]
        card.update({
            "display_name": _display_name(display_index),
            "memory_used_mib": round(used, 2) if used is not None else None,
            "memory_total_mib": round(total, 2),
            "memory_used_gib": round(used / 1024, 2) if used is not None else None,
            "memory_total_gib": round(total / 1024, 2),
            "memory_utilization_percent": round(memory_percent, 2) if memory_percent is not None else None,
            "gpu_utilization_percent": round(min(gpu_percent, 100), 2) if gpu_percent is not None else None,
            "memory_metric_ready": memory_percent is not None,
            "gpu_metric_ready": gpu_percent is not None,
            "health_level": _health_level(gpu_percent, memory_percent),
            "physical_gpu_allocated": None,
        })
    return ordered


def node_gpu_details(node_name, node):
    client, client_error = _client()
    if client_error:
        return _error(client_error, 503)

    results = {}
    diagnostics = []
    for query_key, (vendor, promql) in _instant_queries(node_name).items():
        rows, error = client.query(promql)
        results[query_key] = (vendor, rows or [])
        if error:
            diagnostics.append(query_key)

    cards = _build_realtime_cards(results)
    if not cards and diagnostics:
        return _error("Failed to query physical accelerator metrics", 502, {"failed_queries": diagnostics})

    return _ok({
        "node": node,
        "items": cards,
        "total": len(cards),
        "metric_source": "prometheus",
        "diagnostics": {"failed_queries": diagnostics},
    })


def _timestamp_millis(start_timestamp, bucket_no, bucket_seconds):
    return int((start_timestamp + bucket_no * bucket_seconds) * 1000)


def _datetime_or_none(value):
    return value if isinstance(value, datetime) else None


def _build_history_series(rows, start_timestamp, bucket_seconds, bucket_count):
    cards = {}
    populated_buckets = set()

    for row in rows or []:
        card_id = str(row.get("card_id") or "").strip()
        vendor = str(row.get("vendor") or "").strip()
        try:
            bucket_no = int(row.get("bucket_no"))
        except (TypeError, ValueError):
            continue
        if not card_id or not vendor or not 0 <= bucket_no < bucket_count:
            continue

        card = cards.setdefault((vendor, card_id), {
            "card_id": card_id,
            "vendor": vendor,
            "device_index": (
                int(row["device_index"])
                if row.get("device_index") is not None
                else 10 ** 9
            ),
            "device": str(row.get("device_name") or ""),
            "display_name": "",
            "model": str(row.get("model_name") or "Unknown"),
            "buckets": {},
        })
        average = _float_value(row.get("utilization_avg"))
        maximum = _float_value(row.get("utilization_max"))
        card["buckets"][bucket_no] = {
            "average": (
                round(min(max(average, 0), 100), 2)
                if average is not None
                else None
            ),
            "maximum": (
                round(min(max(maximum, 0), 100), 2)
                if maximum is not None
                else None
            ),
            "sample_count": int(row.get("sample_count") or 0),
        }
        if average is not None:
            populated_buckets.add(bucket_no)

    series = []
    ordered = sorted(
        cards.values(),
        key=lambda item: (
            item["vendor"],
            item["device_index"],
            item["card_id"],
        ),
    )
    for display_index, card in enumerate(ordered):
        points = []
        max_points = []
        sample_counts = []
        for bucket_no in range(bucket_count):
            timestamp = _timestamp_millis(
                start_timestamp,
                bucket_no,
                bucket_seconds,
            )
            bucket = card["buckets"].get(bucket_no) or {}
            points.append([timestamp, bucket.get("average")])
            max_points.append([timestamp, bucket.get("maximum")])
            sample_counts.append([timestamp, int(bucket.get("sample_count") or 0)])
        card.pop("buckets", None)
        card["display_name"] = _display_name(display_index)
        card["points"] = points
        card["max_points"] = max_points
        card["sample_counts"] = sample_counts
        series.append(card)

    return series, populated_buckets


def node_gpu_trend(node_name, metric, range_key, node, now_seconds=None):
    if metric not in TREND_METRICS:
        return _error("metric must be memory_utilization", 400)
    if range_key not in TREND_RANGES:
        return _error("range must be 1h, 24h or 7d", 400)

    config = TREND_RANGES[range_key]
    end = int(now_seconds if now_seconds is not None else time.time())
    start = end - config["seconds"]
    bucket_count = int(config["seconds"] / config["step"])
    bucket_result = load_accelerator_trend_buckets(
        _accelerator_history_cluster_name(),
        node_name,
        datetime.fromtimestamp(start),
        datetime.fromtimestamp(end),
        config["step"],
    )
    if bucket_result.get("error"):
        return _error(
            "Failed to query physical accelerator history",
            503,
            {"history_error": bucket_result["error"]},
        )

    series, populated_buckets = _build_history_series(
        bucket_result.get("items") or [],
        start,
        config["step"],
        bucket_count,
    )
    actual_start = _datetime_or_none(bucket_result.get("actual_start_at"))
    actual_end = _datetime_or_none(bucket_result.get("actual_end_at"))
    history_complete = bool(series) and all(
        all(point[1] is not None for point in item["points"])
        for item in series
    )

    return _ok({
        "node": node,
        "metric": metric,
        "range": range_key,
        "start_timestamp": start * 1000,
        "end_timestamp": end * 1000,
        "step_seconds": config["step"],
        "series": series,
        "total": len(series),
        "metric_source": "mysql_accelerator_history",
        "data_source": "accelerator_metric_sample",
        "expected_bucket_count": bucket_count,
        "populated_bucket_count": len(populated_buckets),
        "raw_sample_count": int(bucket_result.get("raw_sample_count") or 0),
        "actual_start_timestamp": (
            int(actual_start.timestamp() * 1000) if actual_start else None
        ),
        "actual_end_timestamp": (
            int(actual_end.timestamp() * 1000) if actual_end else None
        ),
        "history_complete": history_complete,
        "diagnostics": {"history_error": None},
    })

