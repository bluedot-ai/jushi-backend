import json
from datetime import datetime

try:
    from backend.db.mysql import get_connection
except ModuleNotFoundError:
    from db.mysql import get_connection


OPTIONAL_COLUMNS = {
    "cluster_name": "VARCHAR(128) NULL",
    "namespace": "VARCHAR(128) NULL",
    "instance_name": "VARCHAR(128) NULL",
    "deployment_name": "VARCHAR(128) NULL",
    "fingerprint": "VARCHAR(255) NULL",
    "last_seen_at": "DATETIME NULL",
    "handled_at": "DATETIME NULL",
    "evidence": "JSON NULL",
    "occurrence_count": "INT NOT NULL DEFAULT 1",
}


def ensure_alert_schema() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE alert_event MODIFY alert_type VARCHAR(64) NULL")
            cur.execute("SHOW COLUMNS FROM alert_event")
            existing = {row["Field"] for row in cur.fetchall() or []}
            for column, definition in OPTIONAL_COLUMNS.items():
                if column not in existing:
                    cur.execute(f"ALTER TABLE alert_event ADD COLUMN {column} {definition}")
            cur.execute("SHOW INDEX FROM alert_event WHERE Key_name = 'idx_alert_cluster_namespace'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE alert_event ADD INDEX idx_alert_cluster_namespace (cluster_name, namespace)")
            cur.execute("SHOW INDEX FROM alert_event WHERE Key_name = 'uk_alert_fingerprint'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE alert_event ADD UNIQUE KEY uk_alert_fingerprint (fingerprint)")


def _fmt_dt(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return str(val)


def _row_to_alert(row: dict) -> dict:
    return {
        "id": str(row.get("id")),
        "alert_type": row.get("alert_type"),
        "alert_level": row.get("alert_level"),
        "level": row.get("alert_level"),
        "title": row.get("title"),
        "message": row.get("message"),
        "description": row.get("message"),
        "source": row.get("source"),
        "target_name": row.get("target_name"),
        "target": row.get("target_name"),
        "cluster_name": row.get("cluster_name"),
        "namespace": row.get("namespace"),
        "instance_name": row.get("instance_name") or row.get("target_name"),
        "deployment_name": row.get("deployment_name"),
        "display_status": "异常" if row.get("alert_level") == "high" else "等待",
        "status": row.get("status"),
        "created_at": _fmt_dt(row.get("created_at")),
        "last_seen_at": _fmt_dt(row.get("last_seen_at")),
        "handled_at": _fmt_dt(row.get("handled_at")),
        "resolved_at": _fmt_dt(row.get("resolved_at")),
        "resolver": row.get("resolver"),
        "occurrence_count": row.get("occurrence_count") or 1,
        "evidence": row.get("evidence"),
    }


def _workload_name(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    parts = text.rsplit("-", 2)
    if (
        len(parts) == 3
        and len(parts[1]) >= 6
        and len(parts[2]) >= 4
        and parts[1].replace("-", "").isalnum()
        and parts[2].isalnum()
    ):
        return parts[0]
    return text


def _alert_group_key(row: dict) -> str:
    target = row.get("deployment_name") or row.get("instance_name") or row.get("target_name") or ""
    return "|".join(
        [
            row.get("cluster_name") or "",
            row.get("namespace") or "",
            row.get("alert_type") or "",
            _workload_name(target),
        ]
    )


def upsert_detected_alerts(alerts: list[dict]) -> int:
    if not alerts:
        return 0
    ensure_alert_schema()
    affected = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for alert in alerts:
                cur.execute(
                    """
                    INSERT INTO alert_event (
                        alert_type,
                        alert_level,
                        title,
                        message,
                        source,
                        target_name,
                        cluster_name,
                        namespace,
                        instance_name,
                        deployment_name,
                        fingerprint,
                        last_seen_at,
                        evidence,
                        occurrence_count,
                        status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, 1, 'open')
                    ON DUPLICATE KEY UPDATE
                        alert_level = IF(status IN ('ignored', 'resolved'), alert_level, VALUES(alert_level)),
                        title = IF(status IN ('ignored', 'resolved'), title, VALUES(title)),
                        message = IF(status IN ('ignored', 'resolved'), message, VALUES(message)),
                        source = IF(status IN ('ignored', 'resolved'), source, VALUES(source)),
                        target_name = IF(status IN ('ignored', 'resolved'), target_name, VALUES(target_name)),
                        cluster_name = IF(status IN ('ignored', 'resolved'), cluster_name, VALUES(cluster_name)),
                        namespace = IF(status IN ('ignored', 'resolved'), namespace, VALUES(namespace)),
                        instance_name = IF(status IN ('ignored', 'resolved'), instance_name, VALUES(instance_name)),
                        deployment_name = IF(status IN ('ignored', 'resolved'), deployment_name, VALUES(deployment_name)),
                        last_seen_at = IF(status IN ('ignored', 'resolved'), last_seen_at, NOW()),
                        evidence = IF(status IN ('ignored', 'resolved'), evidence, VALUES(evidence)),
                        occurrence_count = IF(status IN ('ignored', 'resolved'), occurrence_count, occurrence_count + 1),
                        status = IF(status IN ('ignored', 'resolved'), status, 'open'),
                        resolved_at = IF(status IN ('ignored', 'resolved'), resolved_at, NULL),
                        handled_at = IF(status IN ('ignored', 'resolved'), handled_at, NULL),
                        resolver = IF(status IN ('ignored', 'resolved'), resolver, NULL)
                    """,
                    (
                        alert.get("alert_type"),
                        alert.get("alert_level", "medium"),
                        alert.get("title", ""),
                        alert.get("message", ""),
                        alert.get("source", "k8s"),
                        alert.get("target_name"),
                        alert.get("cluster_name"),
                        alert.get("namespace"),
                        alert.get("instance_name"),
                        alert.get("deployment_name"),
                        alert.get("fingerprint"),
                        json.dumps(alert.get("evidence") or {}, ensure_ascii=False),
                    ),
                )
                affected += cur.rowcount
    return affected


def list_alerts(query: dict):
    ensure_alert_schema()
    conditions = []
    params = []
    level = query.get("level")
    if level and level != "all":
        conditions.append("alert_level = %s")
        params.append(level)
    if query.get("status"):
        conditions.append("status = %s")
        params.append(query["status"])
    else:
        conditions.append("status = 'open'")
    if query.get("deployment_name"):
        conditions.append("deployment_name = %s")
        params.append(query["deployment_name"])
    if query.get("cluster_name"):
        conditions.append("cluster_name = %s")
        params.append(query["cluster_name"])
    if query.get("namespace") and query.get("namespace") != "all":
        conditions.append("namespace = %s")
        params.append(query["namespace"])

    page = max(int(query.get("page") or 1), 1)
    page_size = max(min(int(query.get("page_size") or query.get("limit") or 20), 100), 1)
    offset = (page - 1) * page_size
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    handled_conditions = ["status IN ('resolved', 'ignored')"]
    handled_params = []
    if query.get("cluster_name"):
        handled_conditions.append("cluster_name = %s")
        handled_params.append(query["cluster_name"])
    if query.get("namespace") and query.get("namespace") != "all":
        handled_conditions.append("namespace = %s")
        handled_params.append(query["namespace"])
    handled_where_sql = f"WHERE {' AND '.join(handled_conditions)}"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT *
                FROM alert_event
                {where_sql}
                ORDER BY
                    CASE alert_level
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2
                        WHEN 'low' THEN 3
                        ELSE 4
                    END,
                    last_seen_at DESC,
                    created_at DESC
                """,
                tuple(params),
            )
            open_rows = cur.fetchall() or []
            cur.execute(
                f"""
                SELECT *
                FROM alert_event
                {handled_where_sql}
                """,
                tuple(handled_params),
            )
            handled_rows = cur.fetchall() or []

    handled_keys = set()
    for row in handled_rows:
        key = _alert_group_key(row)
        if key:
            handled_keys.add(key)
    rows = [row for row in open_rows if _alert_group_key(row) not in handled_keys]
    total = len(rows)
    page_rows = rows[offset : offset + page_size]

    open_total = total
    high_count = sum(1 for row in rows if row.get("alert_level") == "high")
    medium_count = sum(1 for row in rows if row.get("alert_level") == "medium")
    low_count = sum(1 for row in rows if row.get("alert_level") == "low")
    health_score = max(0, 100 - high_count * 7 - medium_count * 4 - low_count * 2)
    return {
        "items": [_row_to_alert(row) for row in page_rows],
        "summary": {
            "open_total": open_total,
            "high": high_count,
            "medium": medium_count,
            "low": low_count,
            "avg_handle_minutes": 7,
            "health_score": health_score,
        },
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_alert_history(query: dict):
    ensure_alert_schema()
    conditions = []
    params = []
    statuses = query.get("statuses") or ["resolved", "ignored"]
    placeholders = ", ".join(["%s"] * len(statuses))
    conditions.append(f"status IN ({placeholders})")
    params.extend(statuses)

    level = query.get("level")
    if level and level != "all":
        conditions.append("alert_level = %s")
        params.append(level)
    if query.get("deployment_name"):
        conditions.append("deployment_name = %s")
        params.append(query["deployment_name"])
    if query.get("cluster_name"):
        conditions.append("cluster_name = %s")
        params.append(query["cluster_name"])
    if query.get("namespace") and query.get("namespace") != "all":
        conditions.append("namespace = %s")
        params.append(query["namespace"])

    page = max(int(query.get("page") or 1), 1)
    page_size = max(min(int(query.get("page_size") or query.get("limit") or 20), 100), 1)
    offset = (page - 1) * page_size
    where_sql = f"WHERE {' AND '.join(conditions)}"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    SUM(status = 'resolved') AS resolved_count,
                    SUM(status = 'ignored') AS ignored_count
                FROM alert_event
                {where_sql}
                """,
                tuple(params),
            )
            summary = cur.fetchone() or {}
            cur.execute(f"SELECT COUNT(*) AS total FROM alert_event {where_sql}", tuple(params))
            total = (cur.fetchone() or {}).get("total", 0)
            cur.execute(
                f"""
                SELECT *
                FROM alert_event
                {where_sql}
                ORDER BY
                    COALESCE(handled_at, resolved_at, last_seen_at, created_at) DESC,
                    id DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params + [page_size, offset]),
            )
            rows = cur.fetchall() or []

    return {
        "items": [_row_to_alert(row) for row in rows],
        "summary": {
            "resolved": int(summary.get("resolved_count") or 0),
            "ignored": int(summary.get("ignored_count") or 0),
        },
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def create_alert(payload: dict):
    ensure_alert_schema()
    fingerprint = payload.get("fingerprint") or (
        f"manual:{payload.get('cluster_name') or 'cluster'}:"
        f"{payload.get('namespace') or 'default'}:"
        f"{payload.get('deployment_name') or payload.get('target_name') or datetime.now().timestamp()}"
    )
    upsert_detected_alerts([{**payload, "fingerprint": fingerprint, "source": payload.get("source") or "manual"}])
    return {"is_success": True, "fingerprint": fingerprint}


def update_alert_status(payload: dict, status: str):
    ensure_alert_schema()
    alert_id = payload.get("id")
    resolver = payload.get("resolver", "")
    if not alert_id:
        return {"is_success": False, "msg": "id cannot be empty"}

    handled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status in {"resolved", "ignored"} else None
    resolved_at = handled_at if status == "resolved" else None
    saved_resolver = resolver if status in {"resolved", "ignored"} else None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM alert_event WHERE id = %s", (alert_id,))
            target_row = cur.fetchone()
            if not target_row:
                return {"is_success": False, "msg": "alert not found", "id": str(alert_id)}
            ids = [alert_id]
            if status in {"resolved", "ignored"}:
                target_key = _alert_group_key(target_row)
                cur.execute(
                    """
                    SELECT *
                    FROM alert_event
                    WHERE status = 'open'
                      AND alert_type = %s
                      AND COALESCE(cluster_name, '') = %s
                      AND COALESCE(namespace, '') = %s
                    """,
                    (
                        target_row.get("alert_type"),
                        target_row.get("cluster_name") or "",
                        target_row.get("namespace") or "",
                    ),
                )
                ids = [
                    row.get("id")
                    for row in cur.fetchall() or []
                    if _alert_group_key(row) == target_key
                ] or [alert_id]
            placeholders = ", ".join(["%s"] * len(ids))
            cur.execute(
                f"""
                UPDATE alert_event
                SET status = %s, resolver = %s, resolved_at = %s, handled_at = %s
                WHERE id IN ({placeholders})
                """,
                tuple([status, saved_resolver, resolved_at, handled_at] + ids),
            )
            affected_rows = cur.rowcount

    messages = {
        "ignored": "alert ignored",
        "resolved": "alert resolved",
        "open": "alert reopened",
    }
    msg = messages.get(status, "alert status updated")
    return {"is_success": True, "id": str(alert_id), "status": status, "updated": affected_rows, "msg": msg}
