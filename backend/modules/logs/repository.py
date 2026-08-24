import json
import os
import threading
from datetime import datetime, timedelta

try:
    from backend.db.mysql import get_connection
except ModuleNotFoundError:
    from db.mysql import get_connection


_MEMORY_STORE = []
_MEMORY_LOCK = threading.Lock()
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_DATA_FILE = os.path.join(_DATA_DIR, "operation_logs.json")
_TIME_RANGE_DELTAS = {
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _db_available():
    try:
        conn = get_connection()
        conn.close()
        return True
    except Exception:
        return False


def _next_id():
    with _MEMORY_LOCK:
        if not _MEMORY_STORE:
            return 1
        return max(r.get("id", 0) for r in _MEMORY_STORE) + 1


def save_operation_log(record: dict):
    if _db_available():
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO operation_log
                       (operation_type, operator, operator_ip, target_type, target_name,
                        request_payload, response_payload, http_status_code, is_success, error_message)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        record.get("operation_type", ""),
                        record.get("operator", ""),
                        record.get("operator_ip", ""),
                        record.get("target_type", ""),
                        record.get("target_name", ""),
                        record.get("request_payload", ""),
                        record.get("response_payload", ""),
                        record.get("http_status_code", 0),
                        record.get("is_success", 0),
                        record.get("error_message", ""),
                    ),
                )
            return {"is_success": True}
        finally:
            conn.close()

    entry = dict(record)
    entry["id"] = _next_id()
    entry["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _MEMORY_LOCK:
        _MEMORY_STORE.append(entry)
    _save_file(_MEMORY_STORE)
    return {"is_success": True}


def save_external_operation_log(record: dict):
    """写入老脚本上报的操作日志；event_id 保证断线重试不会重复计数。"""
    if _db_available():
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    """INSERT INTO operation_log
                       (event_id, source, operation_type, operator, operator_ip,
                        target_type, target_name, request_payload, response_payload,
                        http_status_code, is_success, error_message, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               COALESCE(%s, CURRENT_TIMESTAMP))
                       ON DUPLICATE KEY UPDATE event_id = VALUES(event_id)""",
                    (
                        record.get("event_id"),
                        record.get("source", "legacy"),
                        record.get("operation_type", ""),
                        record.get("operator", ""),
                        record.get("operator_ip", ""),
                        record.get("target_type", ""),
                        record.get("target_name", ""),
                        record.get("request_payload", ""),
                        record.get("response_payload", ""),
                        record.get("http_status_code", 0),
                        record.get("is_success", 0),
                        record.get("error_message", ""),
                        record.get("created_at"),
                    ),
                )
            return {"is_success": True, "duplicate": affected == 0}
        finally:
            conn.close()

    event_id = record.get("event_id")
    existing_items = _load_memory_logs()
    existing = next(
        (item for item in existing_items if item.get("event_id") == event_id),
        None,
    )
    if existing:
        return {"is_success": True, "duplicate": True}

    entry = dict(record)
    entry["id"] = _next_id()
    entry["created_at"] = _fmt_dt(entry.get("created_at") or datetime.now())
    with _MEMORY_LOCK:
        _MEMORY_STORE.append(entry)
        memory_items = list(_MEMORY_STORE)
    persisted_items = existing_items + [entry] if existing_items else memory_items
    _save_file(persisted_items)
    return {"is_success": True, "duplicate": False}


def list_operation_logs(query: dict):
    if _db_available():
        conn = get_connection()
        try:
            where_clauses, params = _operation_log_filters(query)
            where_sql = " AND ".join(where_clauses)

            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) AS total FROM operation_log WHERE {where_sql}",
                    params,
                )
                total = cur.fetchone()["total"]

                page = query.get("page", 1)
                page_size = query.get("page_size", 100)
                offset = (page - 1) * page_size
                cur.execute(
                    f"SELECT * FROM operation_log WHERE {where_sql} ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                    params + [page_size, offset],
                )
                rows = [_normalize_row(row) for row in cur.fetchall()]
                return {"items": rows, "total": total}
        finally:
            conn.close()

    items = _filter_memory_logs(query)
    total = len(items)
    page = query.get("page", 1)
    page_size = query.get("page_size", 100)
    offset = (page - 1) * page_size
    return {
        "items": [_normalize_row(item) for item in items[offset:offset + page_size]],
        "total": total,
    }


def export_operation_logs(query: dict):
    if _db_available():
        conn = get_connection()
        try:
            where_clauses, params = _operation_log_filters(query)
            where_sql = " AND ".join(where_clauses)

            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM operation_log WHERE {where_sql} ORDER BY created_at DESC, id DESC",
                    params,
                )
                return [_normalize_row(row) for row in cur.fetchall()]
        finally:
            conn.close()

    return [_normalize_row(item) for item in _filter_memory_logs(query)]


def count_operation_calls(operation_types, time_range, end_time=None):
    end_time = end_time or datetime.now()
    cutoff = _time_range_cutoff(time_range, now=end_time)

    if _db_available():
        conn = get_connection()
        try:
            placeholders = ", ".join(["%s"] * len(operation_types))
            where_clauses = [f"operation_type IN ({placeholders})"]
            params = list(operation_types)
            if cutoff is not None:
                where_clauses.append("created_at >= %s")
                params.append(cutoff)
            where_clauses.append("created_at <= %s")
            params.append(end_time)

            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT operation_type,
                               COUNT(*) AS total_calls,
                               SUM(CASE WHEN is_success <> 0 THEN 1 ELSE 0 END) AS success_count,
                               SUM(CASE WHEN is_success = 0 THEN 1 ELSE 0 END) AS failure_count
                        FROM operation_log
                        WHERE {" AND ".join(where_clauses)}
                        GROUP BY operation_type""",
                    params,
                )
                rows = [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
    else:
        allowed_types = set(operation_types)
        rows_by_type = {}
        for item in _load_memory_logs():
            operation_type = item.get("operation_type")
            created_at = _parse_datetime(item.get("created_at"))
            if operation_type not in allowed_types:
                continue
            if cutoff is not None and (created_at is None or created_at < cutoff):
                continue
            if created_at is None or created_at > end_time:
                continue

            counts = rows_by_type.setdefault(operation_type, {
                "operation_type": operation_type,
                "total_calls": 0,
                "success_count": 0,
                "failure_count": 0,
            })
            counts["total_calls"] += 1
            if _is_success_value(item.get("is_success")):
                counts["success_count"] += 1
            else:
                counts["failure_count"] += 1
        rows = list(rows_by_type.values())

    return {
        "rows": rows,
        "start_at": cutoff,
        "end_at": end_time,
    }


def list_audit_envelope(query: dict):
    page = int(query.get("page", 1) or 1)
    page_size = int(query.get("page_size", 100) or 100)
    result = list_operation_logs({
        "operator": query.get("operator", ""),
        "operation_type": query.get("operation_type", ""),
        "keyword": query.get("keyword", ""),
        "operation_result": query.get("operation_result"),
        "time_range": query.get("time_range", "all"),
        "page": page,
        "page_size": page_size,
    })
    return {
        "list": result["items"],
        "total": result["total"],
        "page": page,
        "page_size": page_size,
    }


def _operation_log_filters(query: dict):
    where_clauses = ["1=1"]
    params = []
    if query.get("operator"):
        where_clauses.append("operator = %s")
        params.append(query["operator"])
    if query.get("operation_type"):
        where_clauses.append("operation_type = %s")
        params.append(query["operation_type"])
    if query.get("keyword"):
        where_clauses.append("(target_name LIKE %s OR error_message LIKE %s)")
        kw = f"%{query['keyword']}%"
        params.extend([kw, kw])
    if query.get("operation_result") in (0, 1):
        where_clauses.append("is_success = %s")
        params.append(query["operation_result"])
    cutoff = _time_range_cutoff(query.get("time_range"))
    if cutoff is not None:
        where_clauses.append("created_at >= %s")
        params.append(cutoff)
    return where_clauses, params


def _filter_memory_logs(query: dict):
    items = _load_file()
    if not items:
        with _MEMORY_LOCK:
            items = list(_MEMORY_STORE)

    if query.get("operator"):
        items = [r for r in items if r.get("operator") == query["operator"]]
    if query.get("operation_type"):
        items = [r for r in items if r.get("operation_type") == query["operation_type"]]
    if query.get("keyword"):
        kw = query["keyword"]
        items = [
            r for r in items
            if kw in str(r.get("target_name", "")) or kw in str(r.get("error_message", ""))
        ]
    if query.get("operation_result") in (0, 1):
        expected = bool(query["operation_result"])
        items = [r for r in items if bool(r.get("is_success")) is expected]
    cutoff = _time_range_cutoff(query.get("time_range"))
    if cutoff is not None:
        items = [
            r for r in items
            if (_parse_datetime(r.get("created_at")) or datetime.min) >= cutoff
        ]

    return sorted(items, key=lambda r: r.get("created_at", ""), reverse=True)


def _time_range_cutoff(time_range, now=None):
    delta = _TIME_RANGE_DELTAS.get(str(time_range or "").lower())
    return (now or datetime.now()) - delta if delta is not None else None


def _parse_datetime(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _normalize_row(row):
    item = dict(row or {})
    item["created_at"] = _fmt_dt(item.get("created_at"))
    item["is_success"] = _is_success_value(item.get("is_success"))
    item["operator"] = str(item.get("operator") or "anonymous")
    return item


def _is_success_value(value):
    return value not in (False, 0, "0", "false", None)


def _load_memory_logs():
    items = _load_file()
    if items:
        return items
    with _MEMORY_LOCK:
        return list(_MEMORY_STORE)


def _load_file():
    try:
        with open(_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_file(items: list):
    os.makedirs(_DATA_DIR, exist_ok=True)
    safe = [{k: _fmt_val(v) for k, v in r.items()} for r in items]
    with open(_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(safe, f, ensure_ascii=False, indent=2, default=str)


def _fmt_dt(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return str(val)


def _fmt_val(val):
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return val

