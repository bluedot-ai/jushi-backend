"""MySQL persistence for per-card accelerator history."""

from datetime import datetime, timedelta

try:
    from backend.db.mysql import get_connection
except ModuleNotFoundError:
    from db.mysql import get_connection


UPSERT_SQL = """
    INSERT INTO accelerator_metric_sample (
        sampled_at,
        cluster_name,
        node_name,
        vendor,
        card_id,
        device_index,
        device_name,
        model_name,
        memory_used_mib,
        memory_total_mib,
        memory_utilization_percent,
        metric_source
    )
    VALUES (
        %(sampled_at)s,
        %(cluster_name)s,
        %(node_name)s,
        %(vendor)s,
        %(card_id)s,
        %(device_index)s,
        %(device_name)s,
        %(model_name)s,
        %(memory_used_mib)s,
        %(memory_total_mib)s,
        %(memory_utilization_percent)s,
        %(metric_source)s
    )
    ON DUPLICATE KEY UPDATE
        device_index = VALUES(device_index),
        device_name = VALUES(device_name),
        model_name = VALUES(model_name),
        memory_used_mib = VALUES(memory_used_mib),
        memory_total_mib = VALUES(memory_total_mib),
        memory_utilization_percent = VALUES(memory_utilization_percent),
        metric_source = VALUES(metric_source)
"""


def save_accelerator_samples(samples):
    rows = list(samples or [])
    if not rows:
        return 0, None

    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.executemany(UPSERT_SQL, rows)
        return len(rows), None
    except Exception as exc:
        return 0, str(exc)
    finally:
        if conn is not None:
            conn.close()


def latest_accelerator_sample_time(cluster_name):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT MAX(sampled_at) AS latest_sampled_at
                FROM accelerator_metric_sample
                WHERE cluster_name = %s
                """,
                (cluster_name,),
            )
            row = cursor.fetchone() or {}
        return row.get("latest_sampled_at"), None
    except Exception as exc:
        return None, str(exc)
    finally:
        if conn is not None:
            conn.close()


def load_accelerator_trend_buckets(
    cluster_name,
    node_name,
    start_time,
    end_time,
    bucket_seconds,
):
    empty = {
        "items": [],
        "raw_sample_count": 0,
        "actual_start_at": None,
        "actual_end_at": None,
        "error": None,
    }
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    vendor,
                    card_id,
                    MAX(device_index) AS device_index,
                    MAX(device_name) AS device_name,
                    MAX(model_name) AS model_name,
                    FLOOR(
                        TIMESTAMPDIFF(SECOND, %s, sampled_at) / %s
                    ) AS bucket_no,
                    AVG(memory_utilization_percent) AS utilization_avg,
                    MAX(memory_utilization_percent) AS utilization_max,
                    COUNT(memory_utilization_percent) AS sample_count,
                    MIN(sampled_at) AS first_sample_at,
                    MAX(sampled_at) AS last_sample_at
                FROM accelerator_metric_sample
                WHERE cluster_name = %s
                  AND node_name = %s
                  AND sampled_at >= %s
                  AND sampled_at < %s
                GROUP BY vendor, card_id, bucket_no
                ORDER BY vendor, device_index, card_id, bucket_no
                """,
                (
                    start_time,
                    max(int(bucket_seconds), 1),
                    cluster_name,
                    node_name,
                    start_time,
                    end_time,
                ),
            )
            rows = cursor.fetchall() or []
    except Exception as exc:
        return {**empty, "error": str(exc)}
    finally:
        if conn is not None:
            conn.close()

    if not rows:
        return empty

    valid_times = [
        value
        for row in rows
        for value in (row.get("first_sample_at"), row.get("last_sample_at"))
        if isinstance(value, datetime)
    ]
    return {
        "items": rows,
        "raw_sample_count": sum(int(row.get("sample_count") or 0) for row in rows),
        "actual_start_at": min(valid_times) if valid_times else None,
        "actual_end_at": max(valid_times) if valid_times else None,
        "error": None,
    }


def cleanup_accelerator_samples(retention_days, batch_size=10000):
    cutoff = datetime.now() - timedelta(days=max(int(retention_days), 1))
    deleted = 0
    conn = None
    try:
        conn = get_connection()
        while True:
            with conn.cursor() as cursor:
                affected = cursor.execute(
                    """
                    DELETE FROM accelerator_metric_sample
                    WHERE sampled_at < %s
                    LIMIT %s
                    """,
                    (cutoff, max(int(batch_size), 1)),
                )
            deleted += int(affected or 0)
            if int(affected or 0) < batch_size:
                break
        return deleted, None
    except Exception as exc:
        return deleted, str(exc)
    finally:
        if conn is not None:
            conn.close()

