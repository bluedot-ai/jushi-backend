"""Resource trend construction from complete, bucketed snapshot windows."""

from datetime import datetime, timedelta
from math import ceil

from .constants import METRIC_SOURCE
from .repository import _load_resource_trend_buckets
from .response import _ok
from .trend_cache import (
    CACHED_TREND_RANGES,
    get_cached_trend,
    get_trend_cache_status,
    is_trend_cache_enabled,
    trigger_trend_cache_refresh,
)
from .views import summary


TREND_RANGE_CONFIG = {
    "1h": {"duration": timedelta(hours=1), "bucket_seconds": 60},
    "24h": {"duration": timedelta(hours=24), "bucket_seconds": 15 * 60},
    "7d": {"duration": timedelta(days=7), "bucket_seconds": 60 * 60},
}


def _trend_config(range_value):
    normalized_range = range_value if range_value in TREND_RANGE_CONFIG else "1h"
    return normalized_range, TREND_RANGE_CONFIG[normalized_range]


def _trend_window(range_value):
    normalized_range, config = _trend_config(range_value)
    end_time = datetime.now().replace(microsecond=0)
    start_time = end_time - config["duration"]
    return normalized_range, config, start_time, end_time


def _iso_time(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


def _number(value, digits=2):
    if value is None:
        return None
    try:
        result = round(float(value), digits)
    except (TypeError, ValueError):
        return None
    return int(result) if result.is_integer() else result


def _integer(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _trend_time_label(bucket_start, range_value):
    if range_value == "7d":
        return bucket_start.strftime("%m-%d %H:%M")
    return bucket_start.strftime("%H:%M")


def _empty_trend_item(bucket_no, bucket_start, bucket_end, range_value):
    return {
        "bucket_no": bucket_no,
        "time": _trend_time_label(bucket_start, range_value),
        "bucket_start": _iso_time(bucket_start),
        "bucket_end": _iso_time(bucket_end),
        "last_sample_at": None,
        "sample_count": 0,
        "data_gap": True,
        "gpu_alloc_percent": None,
        "vgpu_alloc_percent": None,
        "gpu_mem_percent": None,
        "gpu_mem_alloc_percent": None,
        "gpu_mem_usage_percent": None,
        "gpu_mem_usage_percent_avg": None,
        "gpu_mem_usage_percent_max": None,
        "gpu_core_percent": None,
        "gpu_core_alloc_percent": None,
        "gpu_core_usage_percent": None,
        "gpu_core_usage_percent_avg": None,
        "gpu_core_usage_percent_max": None,
        "usage_metric_ready": False,
    }


def _trend_item_from_bucket(row, bucket_no, bucket_start, bucket_end, range_value):
    gpu_mem_alloc = _number(row.get("gpu_mem_alloc_percent"))
    gpu_core_alloc = _number(row.get("gpu_core_alloc_percent"))

    return {
        "bucket_no": bucket_no,
        "time": _trend_time_label(bucket_start, range_value),
        "bucket_start": _iso_time(bucket_start),
        "bucket_end": _iso_time(bucket_end),
        "last_sample_at": _iso_time(row.get("last_sample_at")),
        "sample_count": _integer(row.get("sample_count")),
        "data_gap": False,
        "gpu_alloc_percent": _number(row.get("gpu_alloc_percent")),
        "vgpu_alloc_percent": _number(row.get("vgpu_alloc_percent")),
        "gpu_mem_percent": gpu_mem_alloc,
        "gpu_mem_alloc_percent": gpu_mem_alloc,
        "gpu_mem_usage_percent": _number(row.get("gpu_mem_usage_percent_avg")),
        "gpu_mem_usage_percent_avg": _number(row.get("gpu_mem_usage_percent_avg")),
        "gpu_mem_usage_percent_max": _number(row.get("gpu_mem_usage_percent_max")),
        "gpu_core_percent": gpu_core_alloc,
        "gpu_core_alloc_percent": gpu_core_alloc,
        "gpu_core_usage_percent": _number(row.get("gpu_core_usage_percent_avg")),
        "gpu_core_usage_percent_avg": _number(row.get("gpu_core_usage_percent_avg")),
        "gpu_core_usage_percent_max": _number(row.get("gpu_core_usage_percent_max")),
        "usage_metric_ready": bool(_integer(row.get("usage_metric_ready"))),
    }


def _build_trend_items(rows, range_value, start_time, end_time, bucket_seconds):
    bucket_count = int(ceil((end_time - start_time).total_seconds() / bucket_seconds))
    rows_by_bucket = {}
    for row in rows:
        bucket_no = _integer(row.get("bucket_no"), default=-1)
        if 0 <= bucket_no < bucket_count:
            rows_by_bucket[bucket_no] = row

    items = []
    for bucket_no in range(bucket_count):
        bucket_start = start_time + timedelta(seconds=bucket_no * bucket_seconds)
        bucket_end = min(bucket_start + timedelta(seconds=bucket_seconds), end_time)
        row = rows_by_bucket.get(bucket_no)
        if row is None:
            item = _empty_trend_item(
                bucket_no, bucket_start, bucket_end, range_value
            )
        else:
            item = _trend_item_from_bucket(
                row, bucket_no, bucket_start, bucket_end, range_value
            )
        items.append(item)

    return items


def _current_snapshot_item(cards_data, bucket_no, bucket_start, bucket_end, range_value):
    item = _empty_trend_item(
        bucket_no, bucket_start, bucket_end, range_value
    )
    gpu_mem_alloc = _number(cards_data.get("gpu_mem_alloc_percent"))
    gpu_mem_usage = _number(cards_data.get("gpu_mem_usage_percent"))
    gpu_core_alloc = _number(cards_data.get("gpu_core_alloc_percent"))
    item.update({
        "last_sample_at": _iso_time(bucket_end),
        "sample_count": 1,
        "data_gap": False,
        "gpu_alloc_percent": _number(cards_data.get("gpu_alloc_percent")),
        "vgpu_alloc_percent": _number(cards_data.get("vgpu_alloc_percent")),
        "gpu_mem_percent": gpu_mem_alloc,
        "gpu_mem_alloc_percent": gpu_mem_alloc,
        "gpu_mem_usage_percent": gpu_mem_usage,
        "gpu_mem_usage_percent_avg": gpu_mem_usage,
        "gpu_mem_usage_percent_max": gpu_mem_usage,
        "gpu_core_percent": gpu_core_alloc,
        "gpu_core_alloc_percent": gpu_core_alloc,
        "gpu_core_usage_percent": _number(cards_data.get("gpu_core_usage_percent")),
        "gpu_core_usage_percent_avg": _number(cards_data.get("gpu_core_usage_percent")),
        "gpu_core_usage_percent_max": _number(cards_data.get("gpu_core_usage_percent")),
        "usage_metric_ready": bool(cards_data.get("usage_metric_ready", False)),
    })
    return item


def _trend_metadata(
    range_value,
    start_time,
    end_time,
    bucket_seconds,
    items,
    bucket_result,
):
    populated_count = sum(not item["data_gap"] for item in items)
    return {
        "range": range_value,
        "start_at": _iso_time(start_time),
        "end_at": _iso_time(end_time),
        "actual_start_at": _iso_time(bucket_result.get("actual_start_at")),
        "actual_end_at": _iso_time(bucket_result.get("actual_end_at")),
        "bucket_seconds": bucket_seconds,
        "expected_bucket_count": len(items),
        "returned_point_count": len(items),
        "populated_bucket_count": populated_count,
        "data_gap_count": len(items) - populated_count,
        "raw_snapshot_count": _integer(bucket_result.get("raw_snapshot_count")),
        "snapshot_count": _integer(bucket_result.get("raw_snapshot_count")),
        "downsampled": _integer(bucket_result.get("raw_snapshot_count")) > populated_count,
    }


def _build_trend_response(range_value):
    range_value, config, start_time, end_time = _trend_window(range_value)
    bucket_seconds = config["bucket_seconds"]
    bucket_result = _load_resource_trend_buckets(
        "summary", start_time, end_time, bucket_seconds
    )
    rows = bucket_result.get("items") or []
    items = _build_trend_items(
        rows, range_value, start_time, end_time, bucket_seconds
    )
    metadata = _trend_metadata(
        range_value,
        start_time,
        end_time,
        bucket_seconds,
        items,
        bucket_result,
    )

    if rows:
        return _ok({
            **metadata,
            "items": items,
            "data_source": "resource_snapshot",
            "metric_source": METRIC_SOURCE,
            "usage_metric_ready": any(
                item.get("usage_metric_ready") for item in items
            ),
            "need_history_collector": False,
            "history_error": bool(bucket_result.get("error")),
            "note": "Trend data covers the complete requested window and is bucketed in MySQL.",
        })

    summary_result = summary({})
    if not summary_result.get("is_success"):
        return summary_result

    cards_data = summary_result.get("cards", {})
    last_item = items[-1]
    items[-1] = _current_snapshot_item(
        cards_data,
        last_item["bucket_no"],
        datetime.strptime(last_item["bucket_start"], "%Y-%m-%d %H:%M:%S"),
        end_time,
        range_value,
    )
    metadata.update({
        "populated_bucket_count": 1,
        "data_gap_count": max(len(items) - 1, 0),
        "returned_point_count": len(items),
        "downsampled": False,
    })

    return _ok({
        **metadata,
        "items": items,
        "data_source": "current_resource_snapshot",
        "metric_source": METRIC_SOURCE,
        "usage_metric_ready": bool(cards_data.get("usage_metric_ready", False)),
        "need_history_collector": True,
        "history_error": bool(bucket_result.get("error")),
        "note": "No historical samples were found. Only the latest bucket contains current data.",
    })


def _cache_pending_response(range_value, config):
    _, _, start_time, end_time = _trend_window(range_value)
    bucket_seconds = config["bucket_seconds"]
    expected_count = int(config["duration"].total_seconds() / bucket_seconds)
    cache_status = get_trend_cache_status(range_value) or {}
    return _ok({
        "range": range_value,
        "start_at": _iso_time(start_time),
        "end_at": _iso_time(end_time),
        "actual_start_at": None,
        "actual_end_at": None,
        "bucket_seconds": bucket_seconds,
        "expected_bucket_count": expected_count,
        "returned_point_count": 0,
        "populated_bucket_count": 0,
        "data_gap_count": expected_count,
        "raw_snapshot_count": 0,
        "snapshot_count": 0,
        "downsampled": False,
        "items": [],
        "data_source": "trend_cache",
        "metric_source": METRIC_SOURCE,
        "usage_metric_ready": False,
        "need_history_collector": False,
        "retry_after_seconds": 1,
        "note": "Trend cache is warming. Retry shortly.",
        **cache_status,
    })


def trend(query):
    range_value, config = _trend_config(query.get("range"))

    if range_value in CACHED_TREND_RANGES and is_trend_cache_enabled():
        cached = get_cached_trend(range_value)
        if cached is not None:
            return cached
        trigger_trend_cache_refresh(range_value)
        return _cache_pending_response(range_value, config)

    result = _build_trend_response(range_value)
    result.update({
        "cache_hit": False,
        "cache_ready": True,
        "cache_status": "bypass",
        "cache_generated_at": None,
        "cache_age_seconds": 0,
        "cache_refresh_seconds": None,
        "cache_refreshing": False,
        "cache_last_error": False,
    })
    return result

