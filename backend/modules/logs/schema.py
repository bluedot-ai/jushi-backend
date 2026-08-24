import re
import uuid
from datetime import datetime

from .constants import DEPLOY_OPERATION_PATHS


TIME_RANGES = {"all", "1h", "1d", "7d", "30d"}
_SOURCE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _bounded_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min(parsed, maximum), minimum)


def normalize_operation_result(value):
    normalized = str(value or "").strip().lower()
    if normalized in {"success", "true", "1", "成功", "通过"}:
        return 1
    if normalized in {"failure", "failed", "false", "0", "失败"}:
        return 0
    return None


def normalize_time_range(value, default="all"):
    normalized = str(value or default).strip().lower()
    return normalized if normalized in TIME_RANGES else default


def normalize_log_query(args) -> dict:
    page = _bounded_int(args.get("page", 1), 1, 1, 1_000_000)
    page_size = _bounded_int(args.get("page_size", 100), 100, 1, 100)
    return {
        "namespace": args.get("namespace"),
        "pod_name": args.get("pod_name"),
        "deployment_name": args.get("deployment_name"),
        "tail_lines": _bounded_int(args.get("tail_lines", 200), 200, 1, 5000),
        "operator": args.get("operator", ""),
        "operation_type": args.get("operation_type", ""),
        "keyword": args.get("keyword", ""),
        "operation_result": normalize_operation_result(args.get("operation_result")),
        "time_range": normalize_time_range(args.get("time_range")),
        "page": page,
        "page_size": page_size,
    }


def normalize_legacy_audit_event(payload):
    if not isinstance(payload, dict):
        return None, "request body must be a JSON object"

    event_id = str(payload.get("event_id") or "").strip()
    try:
        event_id = str(uuid.UUID(event_id))
    except (ValueError, AttributeError, TypeError):
        return None, "event_id must be a valid UUID"

    source = str(payload.get("source") or "").strip()
    if not _SOURCE_PATTERN.fullmatch(source):
        return None, "source must contain 1-64 letters, numbers, dots, underscores or hyphens"

    path = str(payload.get("path") or "").strip().rstrip("/")
    if path not in DEPLOY_OPERATION_PATHS:
        return None, "path is not one of the six supported deploy endpoints"

    method = str(payload.get("method") or "").strip().upper()
    if method != "POST":
        return None, "method must be POST"

    try:
        http_status_code = int(payload.get("http_status_code"))
    except (TypeError, ValueError):
        return None, "http_status_code must be an integer"
    if not 100 <= http_status_code <= 599:
        return None, "http_status_code must be between 100 and 599"

    is_success = payload.get("is_success")
    if not isinstance(is_success, bool):
        return None, "is_success must be a boolean"

    occurred_at = payload.get("occurred_at")
    if occurred_at:
        try:
            occurred_at = datetime.strptime(
                str(occurred_at).strip(),
                "%Y-%m-%d %H:%M:%S",
            )
        except ValueError:
            return None, "occurred_at must use YYYY-MM-DD HH:MM:SS"
    else:
        occurred_at = None

    request_payload = payload.get("request_payload")
    response_payload = payload.get("response_payload")
    if request_payload is not None and not isinstance(request_payload, (dict, list)):
        return None, "request_payload must be a JSON object or array"
    if response_payload is not None and not isinstance(response_payload, (dict, list)):
        return None, "response_payload must be a JSON object or array"

    return {
        "event_id": event_id,
        "source": source,
        "path": path,
        "method": method,
        "operator": _bounded_text(payload.get("operator"), 64, "legacy-system"),
        "operator_ip": _bounded_text(payload.get("operator_ip"), 64),
        "target_name": _bounded_text(payload.get("target_name"), 128),
        "http_status_code": http_status_code,
        "is_success": is_success,
        "error_message": _bounded_text(payload.get("error_message"), 4096),
        "request_payload": request_payload or {},
        "response_payload": response_payload or {},
        "occurred_at": occurred_at,
    }, None


def _bounded_text(value, maximum, default=""):
    normalized = str(value or default).strip()
    return normalized[:maximum]

