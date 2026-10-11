"""Persistence for cluster-level physical GPU allocation history.

Times are naive Asia/Shanghai wall times, matching the collector and existing DB.
No schema creation occurs on API requests; deployment applies the migration first.
"""

from datetime import datetime, timedelta, timezone

try:
    from backend.db.mysql import get_connection
except ModuleNotFoundError:
    from db.mysql import get_connection


SNAPSHOT_FIELDS = (
    "sampled_at", "sample_slot", "cluster_name", "vendor", "gpu_capacity", "gpu_allocatable",
    "gpu_allocated", "allocation_rate", "gpu_utilization_avg",
    "gpu_utilization_max", "gpu_memory_utilization", "gpu_active_count",
    "allocation_source", "monitor_source", "allocation_valid", "monitor_valid",
    "calculation_version", "sample_interval_seconds",
)
UPSERT_SQL = (
    "INSERT INTO gpu_allocation_snapshot (" + ", ".join(SNAPSHOT_FIELDS) + ") "
    "VALUES (" + ", ".join("%(" + field + ")s" for field in SNAPSHOT_FIELDS) + ") "
    "ON DUPLICATE KEY UPDATE " + ", ".join(
        field + " = VALUES(" + field + ")"
        for field in SNAPSHOT_FIELDS if field not in ("cluster_name", "vendor", "sample_slot")
    )
)
MAX_QUERY_ROWS = 150000


def save_snapshot(snapshot):
    conn = None
    try:
        row = {field: snapshot.get(field) for field in SNAPSHOT_FIELDS}
        row["vendor"] = row["vendor"] or ("nvidia" if row["calculation_version"] == "physical-gpu-v1" else "all")
        if row["vendor"] not in ("all", "nvidia", "ascend"):
            return "GPU 历史快照厂商范围无效"
        row["sample_interval_seconds"] = row["sample_interval_seconds"] or 300
        if row["sample_slot"] is None and isinstance(row["sampled_at"], datetime):
            sampled_at = row["sampled_at"]
            if sampled_at.tzinfo is not None:
                sampled_at = sampled_at.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
                row["sampled_at"] = sampled_at
            epoch = datetime(1970, 1, 1)
            seconds = (sampled_at - epoch).total_seconds()
            interval = max(int(row["sample_interval_seconds"]), 60)
            row["sample_slot"] = epoch + timedelta(seconds=seconds // interval * interval)
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(UPSERT_SQL, row)
        return None
    except Exception:
        # Database errors can contain addresses and credentials; never return them.
        return "GPU 历史快照写入失败，请检查数据库迁移和服务日志"
    finally:
        if conn is not None:
            conn.close()


def load_snapshots(cluster_name, start, end, vendor="all"):
    """Fetch bounded history plus its immediate neighbors for integration."""
    conn = None
    try:
        if vendor not in ("all", "nvidia", "ascend"):
            return [], "GPU 历史查询厂商范围无效"
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM gpu_allocation_snapshot "
                "WHERE cluster_name = %s AND vendor = %s AND sampled_at < %s "
                "ORDER BY sampled_at DESC LIMIT 1", (cluster_name, vendor, start),
            )
            before = cursor.fetchone()
            cursor.execute(
                "SELECT * FROM gpu_allocation_snapshot "
                "WHERE cluster_name = %s AND vendor = %s AND sampled_at >= %s AND sampled_at < %s "
                "ORDER BY sampled_at LIMIT %s", (cluster_name, vendor, start, end, MAX_QUERY_ROWS + 1),
            )
            rows = list(cursor.fetchall() or [])
            if len(rows) > MAX_QUERY_ROWS:
                return [], "GPU 历史数据过多，请缩短查询时间范围"
            cursor.execute(
                "SELECT * FROM gpu_allocation_snapshot "
                "WHERE cluster_name = %s AND vendor = %s AND sampled_at >= %s "
                "ORDER BY sampled_at LIMIT 1", (cluster_name, vendor, end),
            )
            after = cursor.fetchone()
        return ([before] if before else []) + rows + ([after] if after else []), None
    except Exception:
        return [], "GPU 历史查询失败，请检查数据库迁移和服务日志"
    finally:
        if conn is not None:
            conn.close()


def cleanup_snapshots(cutoff, batch_size=1000, max_batches=10):
    """Limit each cleanup pass, preventing an unbounded long-running deletion."""
    conn = None
    deleted = 0
    try:
        batch_size = min(max(int(batch_size), 1), 10000)
        max_batches = min(max(int(max_batches), 1), 100)
        conn = get_connection()
        for _ in range(max_batches):
            with conn.cursor() as cursor:
                affected = cursor.execute(
                    "DELETE FROM gpu_allocation_snapshot WHERE sampled_at < %s "
                    "ORDER BY sampled_at LIMIT %s", (cutoff, batch_size),
                )
            deleted += affected
            if affected < batch_size:
                break
        return deleted, None
    except Exception:
        return deleted, "GPU 历史清理失败，请检查服务日志"
    finally:
        if conn is not None:
            conn.close()
