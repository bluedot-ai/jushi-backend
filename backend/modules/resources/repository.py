"""Persistence adapter for resource snapshots."""

import json
from datetime import datetime, timedelta

try:
    from backend.db.mysql import get_connection
except ModuleNotFoundError:
    from db.mysql import get_connection

from .settings import _snapshot_enabled, _snapshot_interval_seconds, _snapshot_retention_days


def _cleanup_old_resource_snapshots(cursor):
    days = _snapshot_retention_days()
    if days <= 0:
        return

    cutoff = datetime.now() - timedelta(days=days)
    cursor.execute(
        """
        DELETE FROM resource_snapshot
        WHERE created_at < %s
        """,
        (cutoff,),
    )


def _json_dumps(data):
    return json.dumps(data, ensure_ascii=False, default=str)


def _json_loads(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return {}


def _to_datetime(value):
    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value[:19], fmt)
            except ValueError:
                continue

    return None


def _save_resource_snapshot(snapshot_type, payload):
    """
    保存资源快照到 resource_snapshot。

    注意：
    1. 这个动作不能影响主接口返回，所以所有异常都吞掉。
    2. 默认同一种 snapshot_type 每 10 秒最多写一次，避免前端刷新导致数据库爆量。
    3. 每次成功写入后，顺带清理过期快照，默认保留 7 天。
    """
    if not _snapshot_enabled():
        return False

    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT created_at
                FROM resource_snapshot
                WHERE snapshot_type = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (snapshot_type,),
            )
            latest = cursor.fetchone()

            latest_time = _to_datetime(latest.get("created_at")) if latest else None
            if latest_time:
                elapsed = (datetime.now() - latest_time).total_seconds()
                if elapsed < _snapshot_interval_seconds():
                    return False

            cursor.execute(
                """
                INSERT INTO resource_snapshot (snapshot_type, payload)
                VALUES (%s, %s)
                """,
                (snapshot_type, _json_dumps(payload)),
            )

            _cleanup_old_resource_snapshots(cursor)

            return True
    except Exception:
        return False


def _load_resource_snapshots(snapshot_type, start_time, limit=500):
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT payload, created_at
                FROM resource_snapshot
                WHERE snapshot_type = %s
                  AND created_at >= %s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (snapshot_type, start_time, int(limit)),
            )
            rows = cursor.fetchall() or []
    except Exception:
        return []

    result = []
    for row in rows:
        payload = _json_loads(row.get("payload"))
        created_at = _to_datetime(row.get("created_at"))
        if not payload or not created_at:
            continue
        result.append({
            "payload": payload,
            "created_at": created_at,
        })

    return result


def _load_resource_trend_buckets(snapshot_type, start_time, end_time, bucket_seconds):
    """Aggregate the complete time window before limiting the result size."""
    empty_result = {
        "items": [],
        "raw_snapshot_count": 0,
        "actual_start_at": None,
        "actual_end_at": None,
        "error": None,
    }

    try:
        bucket_seconds = max(int(bucket_seconds), 1)
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                WITH extracted AS (
                    SELECT
                        id,
                        created_at,
                        FLOOR(
                            TIMESTAMPDIFF(SECOND, %s, created_at) / %s
                        ) AS bucket_no,
                        CAST(COALESCE(
                            JSON_UNQUOTE(JSON_EXTRACT(payload, '$.cards.gpu_alloc_percent')),
                            '0'
                        ) AS DECIMAL(18, 6)) AS gpu_alloc_percent,
                        CAST(COALESCE(
                            JSON_UNQUOTE(JSON_EXTRACT(payload, '$.cards.vgpu_alloc_percent')),
                            '0'
                        ) AS DECIMAL(18, 6)) AS vgpu_alloc_percent,
                        CAST(COALESCE(
                            JSON_UNQUOTE(JSON_EXTRACT(payload, '$.cards.gpu_mem_alloc_percent')),
                            JSON_UNQUOTE(JSON_EXTRACT(payload, '$.cards.gpu_mem_percent')),
                            '0'
                        ) AS DECIMAL(18, 6)) AS gpu_mem_alloc_percent,
                        CAST(NULLIF(
                            JSON_UNQUOTE(JSON_EXTRACT(payload, '$.cards.gpu_mem_usage_percent')),
                            'null'
                        ) AS DECIMAL(18, 6)) AS recorded_gpu_mem_usage_percent,
                        CAST(NULLIF(
                            JSON_UNQUOTE(JSON_EXTRACT(payload, '$.cards.gpu_mem_used_gib')),
                            'null'
                        ) AS DECIMAL(18, 6)) AS gpu_mem_used_gib,
                        CAST(NULLIF(
                            JSON_UNQUOTE(JSON_EXTRACT(payload, '$.cards.gpu_mem_total_gib')),
                            'null'
                        ) AS DECIMAL(18, 6)) AS gpu_mem_total_gib,
                        CAST(COALESCE(
                            JSON_UNQUOTE(JSON_EXTRACT(payload, '$.cards.gpu_core_alloc_percent')),
                            JSON_UNQUOTE(JSON_EXTRACT(payload, '$.cards.gpu_core_percent')),
                            '0'
                        ) AS DECIMAL(18, 6)) AS gpu_core_alloc_percent,
                        CAST(NULLIF(
                            JSON_UNQUOTE(JSON_EXTRACT(payload, '$.cards.gpu_core_usage_percent')),
                            'null'
                        ) AS DECIMAL(18, 6)) AS gpu_core_usage_percent,
                        CASE
                            WHEN LOWER(COALESCE(
                                JSON_UNQUOTE(JSON_EXTRACT(payload, '$.cards.usage_metric_ready')),
                                'false'
                            )) IN ('true', '1') THEN 1
                            ELSE 0
                        END AS usage_metric_ready
                    FROM resource_snapshot
                    WHERE snapshot_type = %s
                      AND created_at >= %s
                      AND created_at < %s
                ),
                normalized AS (
                    SELECT
                        *,
                        CASE
                            WHEN gpu_mem_total_gib > 0 THEN
                                gpu_mem_used_gib * 100 / gpu_mem_total_gib
                            ELSE recorded_gpu_mem_usage_percent
                        END AS gpu_mem_usage_percent
                    FROM extracted
                ),
                ranked AS (
                    SELECT
                        *,
                        ROW_NUMBER() OVER (
                            PARTITION BY bucket_no
                            ORDER BY created_at DESC, id DESC
                        ) AS row_no,
                        COUNT(*) OVER () AS raw_snapshot_count,
                        MIN(created_at) OVER () AS actual_start_at,
                        MAX(created_at) OVER () AS actual_end_at,
                        COUNT(*) OVER (
                            PARTITION BY bucket_no
                        ) AS sample_count,
                        AVG(gpu_mem_usage_percent) OVER (
                            PARTITION BY bucket_no
                        ) AS gpu_mem_usage_percent_avg,
                        MAX(gpu_mem_usage_percent) OVER (
                            PARTITION BY bucket_no
                        ) AS gpu_mem_usage_percent_max,
                        AVG(gpu_core_usage_percent) OVER (
                            PARTITION BY bucket_no
                        ) AS gpu_core_usage_percent_avg,
                        MAX(gpu_core_usage_percent) OVER (
                            PARTITION BY bucket_no
                        ) AS gpu_core_usage_percent_max,
                        MAX(usage_metric_ready) OVER (
                            PARTITION BY bucket_no
                        ) AS bucket_usage_metric_ready
                    FROM normalized
                )
                SELECT
                    bucket_no,
                    created_at AS last_sample_at,
                    raw_snapshot_count,
                    actual_start_at,
                    actual_end_at,
                    sample_count,
                    gpu_alloc_percent,
                    vgpu_alloc_percent,
                    gpu_mem_alloc_percent,
                    gpu_mem_usage_percent AS gpu_mem_usage_percent_last,
                    gpu_mem_usage_percent_avg,
                    gpu_mem_usage_percent_max,
                    gpu_core_alloc_percent,
                    gpu_core_usage_percent AS gpu_core_usage_percent_last,
                    gpu_core_usage_percent_avg,
                    gpu_core_usage_percent_max,
                    bucket_usage_metric_ready AS usage_metric_ready
                FROM ranked
                WHERE row_no = 1
                ORDER BY bucket_no ASC
                """,
                (
                    start_time,
                    bucket_seconds,
                    snapshot_type,
                    start_time,
                    end_time,
                ),
            )
            rows = cursor.fetchall() or []
    except Exception as exc:
        return {
            **empty_result,
            "error": str(exc),
        }

    if not rows:
        return empty_result

    return {
        "items": rows,
        "raw_snapshot_count": int(rows[0].get("raw_snapshot_count") or 0),
        "actual_start_at": _to_datetime(rows[0].get("actual_start_at")),
        "actual_end_at": _to_datetime(rows[0].get("actual_end_at")),
        "error": None,
    }

