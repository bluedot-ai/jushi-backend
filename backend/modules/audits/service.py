try:
    from backend.modules.logs.constants import DEPLOY_OPERATION_PATHS
    from backend.modules.logs.repository import (
        count_operation_calls,
        export_operation_logs,
        list_audit_envelope,
    )
except ModuleNotFoundError:
    from modules.logs.constants import DEPLOY_OPERATION_PATHS
    from modules.logs.repository import (
        count_operation_calls,
        export_operation_logs,
        list_audit_envelope,
    )


TRACKED_DEPLOY_OPERATIONS = tuple(
    {
        "operation_type": operation_type,
        "method": "POST",
        "path": path,
    }
    for path, operation_type in DEPLOY_OPERATION_PATHS.items()
)


def list_audit_logs(query: dict) -> dict:
    return list_audit_envelope(query)


def export_audit_logs(query: dict) -> list:
    return export_operation_logs(query)


def get_call_statistics(time_range: str) -> dict:
    operation_types = [item["operation_type"] for item in TRACKED_DEPLOY_OPERATIONS]
    result = count_operation_calls(operation_types, time_range)
    rows_by_type = {
        row["operation_type"]: row
        for row in result.get("rows", [])
    }

    items = []
    for operation in TRACKED_DEPLOY_OPERATIONS:
        row = rows_by_type.get(operation["operation_type"], {})
        items.append({
            **operation,
            "total_calls": int(row.get("total_calls") or 0),
            "success_count": int(row.get("success_count") or 0),
            "failure_count": int(row.get("failure_count") or 0),
        })

    return {
        "is_success": True,
        "time_range": time_range,
        "start_at": _format_datetime(result.get("start_at")),
        "end_at": _format_datetime(result.get("end_at")),
        "total_calls": sum(item["total_calls"] for item in items),
        "success_count": sum(item["success_count"] for item in items),
        "failure_count": sum(item["failure_count"] for item in items),
        "items": items,
    }


def _format_datetime(value):
    if value is None:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")

