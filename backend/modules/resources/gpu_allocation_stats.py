"""Time-weighted history and calendar-month comparisons for physical GPUs."""

import math
import os
import re
from datetime import datetime, timedelta, timezone

try:
    from backend.config import Config
except ModuleNotFoundError:
    from config import Config

from .gpu_allocation_repository import load_snapshots
from .response import _error, _ok


TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
CALCULATION_VERSION = "physical-accelerator-v2"
SUPPORTED_VERSIONS = frozenset(("physical-gpu-v1", CALCULATION_VERSION))
AVAILABLE_VENDORS = ("all", "nvidia", "ascend")
MONITOR_WINDOW_SECONDS = 300
METRICS = (
    "gpu_capacity_avg", "gpu_allocatable_avg", "gpu_allocated_avg",
    "allocation_rate_avg", "allocation_rate_max", "gpu_card_hours",
    "gpu_utilization_avg", "gpu_memory_utilization", "allocation_completeness",
    "utilization_completeness", "memory_completeness",
)
PERCENT_METRICS = frozenset(
    ("allocation_rate_avg", "allocation_rate_max", "gpu_utilization_avg",
     "gpu_memory_utilization", "allocation_completeness", "utilization_completeness",
     "memory_completeness")
)


def _now():
    return datetime.now(TIMEZONE).replace(tzinfo=None)


def _shift_month(value, months):
    total = value.year * 12 + value.month - 1 + months
    return datetime(total // 12, total % 12 + 1, 1)


def retention_cutoff(now=None):
    """Scheme B: current month plus preceding six complete calendar months."""
    return _shift_month(now or _now(), -6)


def _iso(value):
    return value.replace(tzinfo=TIMEZONE).isoformat(timespec="seconds")


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _interval(row=None):
    value = _number((row or {}).get("sample_interval_seconds"))
    if value is None:
        value = _number(os.getenv("GPU_ALLOCATION_INTERVAL_SECONDS", "300"))
    return max(int(value or 300), 60)


def _row_time(row):
    value = row.get("sampled_at")
    if isinstance(value, datetime):
        return value.astimezone(TIMEZONE).replace(tzinfo=None) if value.tzinfo else value
    return None


def _row_vendor(row):
    return row.get("vendor") or ("nvidia" if row.get("calculation_version") == "physical-gpu-v1" else "all")


def _allocation_values(row):
    values = [_number(row.get(key)) for key in ("gpu_capacity", "gpu_allocatable", "gpu_allocated")]
    if not row.get("allocation_valid") or any(value is None or value < 0 for value in values):
        return None
    capacity, allocatable, allocated = values
    if allocatable > capacity or allocated > allocatable or any(not value.is_integer() for value in values):
        return None
    # Both numerator and denominator describe the same schedulable node pool.
    return capacity, allocatable, allocated


def _monitor(row, field):
    value = _number(row.get(field))
    return value if value is not None and 0 <= value <= 100 else None


def _sampling_grid(ordered, start, end):
    """Use persisted intervals, not today's config, to count historical slots."""
    preceding = [row for timestamp, row in ordered if timestamp <= start]
    following = [row for timestamp, row in ordered if start < timestamp <= end]
    seed = preceding[-1] if preceding else following[0] if following else None
    interval = _interval(seed)
    segment_start = start
    grid = []
    for timestamp, row in ordered:
        if not start < timestamp < end:
            continue
        new_interval = _interval(row)
        if new_interval != interval:
            grid.append((segment_start, timestamp, interval))
            segment_start, interval = timestamp, new_interval
    if segment_start < end:
        grid.append((segment_start, end, interval))
    expected = sum(math.ceil((right - left).total_seconds() / interval) for left, right, interval in grid)
    return grid, expected


def _sample_slot(timestamp, grid):
    for index, (left, right, interval) in enumerate(grid):
        if left <= timestamp < right:
            return index, int((timestamp - left).total_seconds() // interval)
    return None


def aggregate(rows, start, end, vendor=None):
    """Integrate observed values without bridging stale gaps.

    Allocation is state at sampled_at, held until the next sample. Monitor values
    describe the preceding sample window and are integrated backwards. A gap
    larger than two intervals never gets filled with the preceding allocation.
    """
    unique = {}
    for row in rows:
        row_vendor = _row_vendor(row)
        if vendor is not None and row_vendor != vendor:
            continue
        timestamp = _row_time(row)
        if timestamp is not None:
            unique[timestamp] = row
    ordered = sorted(unique.items())
    grid, expected = _sampling_grid(ordered, start, end)
    result = {key: None for key in METRICS}
    result.update({
        "period_start": _iso(start), "period_end": _iso(end),
        "expected_samples": expected,
        "valid_sample_counts": {key: 0 for key in ("allocation", "utilization", "memory")},
        "coverage_seconds": {key: 0 for key in ("allocation", "utilization", "memory")},
        "actual_start_at": None, "actual_end_at": None,
        "status": "no_data", "calculation_versions": [],
        "calculation_version": None,
        "sampling_intervals": [{"start": _iso(left), "end": _iso(right), "seconds": interval} for left, right, interval in grid],
    })
    relevant = []
    for index, (timestamp, row) in enumerate(ordered):
        interval = _interval(row)
        following = ordered[index + 1][0] if index + 1 < len(ordered) else None
        duration = (following - timestamp).total_seconds() if following else interval
        if duration <= 0 or duration > interval * 2:
            duration = interval
        state_end = timestamp + timedelta(seconds=duration)
        preceding = ordered[index - 1][0] if index else timestamp - timedelta(seconds=MONITOR_WINDOW_SECONDS)
        window_start = max(timestamp - timedelta(seconds=MONITOR_WINDOW_SECONDS), preceding, start)
        state_overlap = timestamp < end and state_end > start and _allocation_values(row) is not None
        monitor_overlap = min(timestamp, end) > window_start and any(
            _monitor(row, field) is not None for field in ("gpu_utilization_avg", "gpu_memory_utilization")
        )
        if state_overlap or monitor_overlap:
            relevant.append(row)
    versions = sorted(set(str(row.get("calculation_version") or "unknown") for row in relevant))
    result["calculation_versions"] = versions
    result["calculation_version"] = versions[0] if len(versions) == 1 else None
    for key in ("allocation", "utilization", "memory"):
        result[key + "_completeness"] = 0.0
    if len(versions) > 1 or any(version not in SUPPORTED_VERSIONS for version in versions):
        result["status"] = "mixed_version" if len(versions) > 1 else "unsupported_version"
        return result

    sums = {key: 0.0 for key in ("capacity", "allocatable", "allocated", "utilization", "memory")}
    coverage = result["coverage_seconds"]
    slots = {key: set() for key in coverage}
    peaks = []
    observation_intervals = []
    for index, (timestamp, row) in enumerate(ordered):
        if row.get("calculation_version") not in SUPPORTED_VERSIONS:
            continue
        allocation = _allocation_values(row)
        util = _monitor(row, "gpu_utilization_avg")
        memory = _monitor(row, "gpu_memory_utilization")
        if start <= timestamp < end:
            slot = _sample_slot(timestamp, grid)
            if allocation is not None:
                slots["allocation"].add(slot)

        interval = _interval(row)
        following = ordered[index + 1][0] if index + 1 < len(ordered) else None
        duration = (following - timestamp).total_seconds() if following else interval
        if duration <= 0 or duration > interval * 2:
            duration = interval
        seconds = max((min(end, timestamp + timedelta(seconds=duration)) - max(start, timestamp)).total_seconds(), 0)
        if allocation is not None and seconds:
            observation_intervals.append((max(start, timestamp), min(end, timestamp + timedelta(seconds=duration))))
            for name, value in zip(("capacity", "allocatable", "allocated"), allocation):
                sums[name] += value * seconds
            coverage["allocation"] += seconds
            if allocation[1] > 0:
                peaks.append(allocation[2] / allocation[1] * 100)

        # Windows are truncated by their predecessor to prevent double counting
        # rapid manual collections or overlapping monitor windows.
        preceding = ordered[index - 1][0] if index else timestamp - timedelta(seconds=MONITOR_WINDOW_SECONDS)
        window_start = max(timestamp - timedelta(seconds=MONITOR_WINDOW_SECONDS), preceding, start)
        seconds = max((min(timestamp, end) - window_start).total_seconds(), 0)
        for name, value in (("utilization", util), ("memory", memory)):
            if value is not None and seconds:
                observation_intervals.append((window_start, min(timestamp, end)))
                sums[name] += value * seconds
                coverage[name] += seconds
                # A monitor sample stamped at 00:05 belongs to the 00:00–00:05
                # slot, including the sample exactly at the query end boundary.
                slot_end = min(timestamp, end)
                slot = _sample_slot(slot_end - timedelta(microseconds=1), grid)
                if slot is not None:
                    slots[name].add(slot)

    for key in coverage:
        result["valid_sample_counts"][key] = len(slots[key])
        result[key + "_completeness"] = round(min(len(slots[key]) / expected * 100, 100), 3) if expected else 0.0
        coverage[key] = round(coverage[key], 3)
    if coverage["allocation"]:
        for metric, name in (("gpu_capacity_avg", "capacity"), ("gpu_allocatable_avg", "allocatable"), ("gpu_allocated_avg", "allocated")):
            result[metric] = round(sums[name] / coverage["allocation"], 4)
        result["allocation_rate_avg"] = round(sums["allocated"] / sums["allocatable"] * 100, 4) if sums["allocatable"] else None
        result["allocation_rate_max"] = round(max(peaks), 4) if peaks else None
        result["gpu_card_hours"] = round(sums["allocated"] / 3600, 4)
    for key, metric in (("utilization", "gpu_utilization_avg"), ("memory", "gpu_memory_utilization")):
        if coverage[key]:
            result[metric] = round(sums[key] / coverage[key], 4)
    if any(coverage.values()):
        result["status"] = "ok"
    if observation_intervals:
        result["actual_start_at"] = _iso(min(left for left, _ in observation_intervals))
        result["actual_end_at"] = _iso(max(right for _, right in observation_intervals))
    return result


def _context(query):
    timezone = query.get("timezone", "Asia/Shanghai")
    if timezone != "Asia/Shanghai":
        raise ValueError("timezone 仅支持 Asia/Shanghai")
    default_cluster = os.getenv("GPU_ALLOCATION_CLUSTER_NAME", Config.DCE_CLUSTER) or "default"
    cluster = str(query.get("cluster_name") or default_cluster).strip()
    if not cluster or len(cluster) > 128 or any(ord(char) < 32 for char in cluster):
        raise ValueError("cluster_name 无效")
    now = _now()
    cutoff = retention_cutoff(now)
    return cluster, now, cutoff


def _vendor(query):
    vendor = query.get("vendor", "all")
    if vendor not in AVAILABLE_VENDORS:
        raise ValueError("vendor 仅支持 all、nvidia 或 ascend")
    return vendor


def _parse(value, pattern, fmt, field):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(field + " 格式无效")
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        raise ValueError(field + " 日期无效") from None


def _metadata(cluster, now, cutoff, vendor="all"):
    return {
        "cluster_name": cluster, "timezone": "Asia/Shanghai",
        "calculation_version": CALCULATION_VERSION,
        "vendor": vendor, "available_vendors": list(AVAILABLE_VENDORS),
        "retention_start": cutoff.strftime("%Y-%m-%d"),
        "available_months": [_shift_month(cutoff, index).strftime("%Y-%m") for index in range(7)],
        "as_of": _iso(now),
        "nominal_interval_seconds": _interval(),
    }


def trend(query):
    try:
        cluster, now, cutoff = _context(query)
        vendor = _vendor(query)
        start = _parse(query.get("start"), r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d", "start")
        requested_end = _parse(query.get("end"), r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d", "end")
        granularity = query.get("granularity", "day")
        if granularity not in ("day", "hour"):
            raise ValueError("granularity 仅支持 day 或 hour")
        if start < cutoff or requested_end > _shift_month(now, 1) or start >= requested_end or start > now:
            raise ValueError("查询范围须在当前月及前六个完整自然月内，且 start 小于 end")
        end = min(requested_end, now)
    except (ValueError, TypeError, AttributeError) as exc:
        return _error(str(exc), 400)
    rows, error = load_snapshots(cluster, start, end, vendor=vendor)
    if error:
        return _error(error, 503)
    step = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
    items = []
    # Restrict each bucket to nearby samples instead of rescanning the entire
    # seven-month history for every hour (up to 5,000 buckets).
    ordered = sorted((row for row in rows if _row_vendor(row) == vendor and _row_time(row) is not None and _row_time(row) <= now), key=_row_time)
    index = 0
    cursor = start
    while cursor < end:
        bucket_end = min(cursor + step, end)
        while index < len(ordered) and _row_time(ordered[index]) < cursor:
            index += 1
        last = index
        while last < len(ordered) and _row_time(ordered[last]) < bucket_end:
            last += 1
        bucket_rows = ordered[max(index - 1, 0):min(last + 1, len(ordered))]
        items.append({"sampled_at": _iso(cursor), "date": cursor.strftime("%Y-%m-%d"), **aggregate(bucket_rows, cursor, bucket_end, vendor=vendor)})
        cursor = bucket_end
    return _ok({"data": {**_metadata(cluster, now, cutoff, vendor), "granularity": granularity, "start": _iso(start), "end": _iso(end), "items": items}})


def compare(query):
    try:
        cluster, now, cutoff = _context(query)
        vendor = _vendor(query)
        months = [
            _parse(query.get(field), r"\d{4}-\d{2}", "%Y-%m", field)
            for field in ("base_month", "compare_month")
        ]
        if any(month < cutoff or month > now for month in months):
            raise ValueError("月份须在当前月及前六个完整自然月内")
    except (ValueError, TypeError, AttributeError) as exc:
        return _error(str(exc), 400)
    summaries = []
    for month in months:
        month_end = _shift_month(month, 1)
        end = min(month_end, now)
        rows, error = load_snapshots(cluster, month, end, vendor=vendor)
        if error:
            return _error(error, 503)
        rows = [row for row in rows if _row_time(row) is not None and _row_time(row) <= now]
        summaries.append({"month": month.strftime("%Y-%m"), "partial_month": end < month_end, **aggregate(rows, month, end, vendor=vendor)})
    base, comparison = summaries
    compatible = base["status"] not in ("mixed_version", "unsupported_version") and comparison["status"] not in ("mixed_version", "unsupported_version")
    if base["calculation_versions"] and comparison["calculation_versions"]:
        compatible = compatible and base["calculation_versions"] == comparison["calculation_versions"]
    changes = {}
    for metric in METRICS:
        old, new = base[metric], comparison[metric]
        valid = compatible and old is not None and new is not None
        changes[metric] = {
            "absolute": round(new - old, 4) if valid else None,
            "percentage": round((new - old) / old * 100, 4) if valid and old != 0 else None,
            "unit": "pp" if metric in PERCENT_METRICS else "GPU·h" if metric == "gpu_card_hours" else "张",
        }
    return _ok({"data": {**_metadata(cluster, now, cutoff, vendor), "base": base, "comparison": comparison, "changes": changes,
                        "comparison_compatible": compatible, "comparison_warning": None if compatible else "calculation_version_mismatch"}})
