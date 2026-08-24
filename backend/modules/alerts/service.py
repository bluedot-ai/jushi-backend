from . import detector, repository


def list_alerts(query: dict) -> dict:
    detected, scan_error, diagnostics = detector.detect_cluster_alerts(query)
    written = repository.upsert_detected_alerts(detected)
    result = repository.list_alerts(query)
    return {
        "is_success": True,
        "scan_error": scan_error,
        "scan_scope": diagnostics,
        "detected": len(detected),
        "written": written,
        **result,
    }


def list_alert_history(query: dict) -> dict:
    result = repository.list_alert_history(query)
    return {"is_success": True, **result}


def create_alert(payload: dict) -> dict:
    return repository.create_alert(payload)


def resolve_alert(payload: dict) -> dict:
    return repository.update_alert_status(payload, "resolved")


def ignore_alert(payload: dict) -> dict:
    return repository.update_alert_status(payload, "ignored")


def reopen_alert(payload: dict) -> dict:
    return repository.update_alert_status(payload, "open")
