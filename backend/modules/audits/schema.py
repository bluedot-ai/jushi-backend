try:
    from backend.modules.logs.schema import (
        TIME_RANGES,
        _bounded_int,
        normalize_operation_result,
        normalize_time_range,
    )
except ModuleNotFoundError:
    from modules.logs.schema import (
        TIME_RANGES,
        _bounded_int,
        normalize_operation_result,
        normalize_time_range,
    )


def normalize_audit_list(payload: dict) -> dict:
    content = (payload or {}).get("content") or {}
    return {
        "operator": content.get("operator", ""),
        "operation_type": content.get("operation_type", ""),
        "keyword": content.get("keyword", ""),
        "operation_result": normalize_operation_result(content.get("operation_result")),
        "time_range": normalize_time_range(content.get("time_range")),
        "page": _bounded_int(content.get("page", 1), 1, 1, 1_000_000),
        "page_size": _bounded_int(content.get("page_size", 100), 100, 1, 100),
    }


def normalize_audit_export(payload: dict) -> dict:
    content = (payload or {}).get("content") or {}
    return {
        "operator": content.get("operator", ""),
        "operation_type": content.get("operation_type", ""),
        "keyword": content.get("keyword", ""),
        "operation_result": normalize_operation_result(content.get("operation_result")),
        "time_range": normalize_time_range(content.get("time_range")),
        "format": "excel" if content.get("format") == "excel" else "json",
    }


def normalize_call_statistics(args):
    time_range = str(args.get("time_range") or "1h").strip().lower()
    if time_range not in TIME_RANGES:
        allowed = ", ".join(("1h", "1d", "7d", "30d", "all"))
        return None, f"time_range must be one of: {allowed}"
    return {"time_range": time_range}, None

