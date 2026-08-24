import json

from . import repository
from .constants import DEPLOY_OPERATION_PATHS

try:
    from backend.config import Config
    from backend.services.k8s_client import K8sClient
except ModuleNotFoundError:
    from config import Config
    from services.k8s_client import K8sClient


def operation_logs(query: dict) -> dict:
    result = repository.list_operation_logs(query)
    return {
        "items": result["items"],
        "total": result["total"],
        "page": query.get("page", 1),
        "page_size": query.get("page_size", 100),
    }


_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "password",
    "passwd",
    "secret",
    "token",
}
_MAX_SNAPSHOT_CHARS = 65535


def ingest_legacy_audit_event(event: dict) -> dict:
    request_payload = _redact_sensitive(event.get("request_payload") or {})
    response_payload = _redact_sensitive(event.get("response_payload") or {})
    record = {
        "event_id": event["event_id"],
        "source": event["source"],
        "operation_type": DEPLOY_OPERATION_PATHS[event["path"]],
        "operator": event.get("operator") or "legacy-system",
        "operator_ip": event.get("operator_ip") or "",
        "target_type": "deploy",
        "target_name": event.get("target_name") or "",
        "request_payload": _json_snapshot(request_payload),
        "response_payload": _json_snapshot(response_payload),
        "http_status_code": event["http_status_code"],
        "is_success": event["is_success"],
        "error_message": event.get("error_message") or "",
        "created_at": event.get("occurred_at"),
    }
    return repository.save_external_operation_log(record)


def _redact_sensitive(value):
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if str(key).lower() in _SENSITIVE_KEYS
                else _redact_sensitive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def _json_snapshot(value):
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    if len(serialized) <= _MAX_SNAPSHOT_CHARS:
        return serialized
    return json.dumps(
        {"truncated": True, "preview": serialized[:_MAX_SNAPSHOT_CHARS]},
        ensure_ascii=False,
    )


def instance_logs(query: dict) -> dict:
    deployment_name = query.get("deployment_name", "")
    if not deployment_name:
        return {"is_success": False, "msg": "deployment_name 不能为空", "lines": []}

    namespace = query.get("namespace") or Config.DCE_NAMESPACE
    tail_lines = int(query.get("tail_lines") or 200)
    client = K8sClient.from_config(Config)
    pod_status, pod_result = client.list_pods_by_app(namespace, deployment_name)
    if not 200 <= pod_status < 300:
        return {
            "is_success": False,
            "msg": "实例 Pod 查询失败",
            "http_status_code": pod_status,
            "response": pod_result,
            "lines": [],
        }

    pods = pod_result.get("items", []) or []
    running = [pod for pod in pods if (pod.get("status") or {}).get("phase") == "Running"]
    target = (running or pods or [None])[0]
    if not target:
        return {"is_success": False, "msg": "实例暂无可读取日志的 Pod", "lines": []}

    pod_name = (target.get("metadata") or {}).get("name")
    log_status, log_result = client.pod_logs(namespace, pod_name, tail_lines=tail_lines)
    if not 200 <= log_status < 300:
        return {
            "is_success": False,
            "msg": "实例日志查询失败",
            "http_status_code": log_status,
            "response": log_result,
            "lines": [],
        }
    raw = log_result.get("raw", "")
    return {"is_success": True, "pod_name": pod_name, "lines": raw.splitlines() if raw else []}


def pod_logs(query: dict) -> dict:
    try:
        from backend.modules.pods.service import pod_logs as _pods_pod_logs
    except ModuleNotFoundError:
        from modules.pods.service import pod_logs as _pods_pod_logs
    return _pods_pod_logs(query)

