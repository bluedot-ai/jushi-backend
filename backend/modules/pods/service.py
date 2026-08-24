try:
    from backend.config import Config
    from backend.services.k8s_client import K8sClient
except ModuleNotFoundError:
    from config import Config
    from services.k8s_client import K8sClient


def _client() -> K8sClient:
    return K8sClient.from_config(Config)


def _namespace(query: dict) -> str:
    return query.get("namespace") or Config.DCE_NAMESPACE


def _container_state(state) -> str:
    if not state:
        return "unknown"
    if "running" in state:
        return "running"
    if "waiting" in state:
        return state["waiting"].get("reason", "waiting")
    if "terminated" in state:
        return state["terminated"].get("reason", "terminated")
    return "unknown"


def _pod_summary(pod: dict) -> dict:
    meta = pod.get("metadata", {}) or {}
    status = pod.get("status", {}) or {}
    spec = pod.get("spec", {}) or {}
    restart_count = 0
    ready = False
    for container_status in status.get("containerStatuses", []) or []:
        restart_count += container_status.get("restartCount", 0) or 0
        if container_status.get("ready"):
            ready = True
    return {
        "pod_name": meta.get("name"),
        "namespace": meta.get("namespace"),
        "phase": status.get("phase"),
        "node_name": spec.get("nodeName"),
        "pod_ip": status.get("podIP"),
        "restart_count": restart_count,
        "ready": ready,
        "created_at": meta.get("creationTimestamp"),
    }


def _event_summary(event: dict) -> dict:
    return {
        "type": event.get("type"),
        "reason": event.get("reason"),
        "message": event.get("message"),
        "first_timestamp": event.get("firstTimestamp") or event.get("eventTime"),
        "last_timestamp": event.get("lastTimestamp") or event.get("eventTime"),
    }


def _pod_detail(pod: dict, events: list[dict]) -> dict:
    detail = _pod_summary(pod)
    status = pod.get("status", {}) or {}
    containers = []
    for container_status in status.get("containerStatuses", []) or []:
        containers.append(
            {
                "name": container_status.get("name"),
                "image": container_status.get("image"),
                "ready": container_status.get("ready"),
                "restart_count": container_status.get("restartCount", 0),
                "state": _container_state(container_status.get("state")),
            }
        )
    detail["host_ip"] = status.get("hostIP")
    detail["containers"] = containers
    detail["events"] = [_event_summary(event) for event in events]
    return detail


def _error_result(msg: str, status_code: int, response=None) -> dict:
    return {
        "is_success": False,
        "msg": msg,
        "http_status_code": status_code,
        "response": response or {},
    }


def list_pods(query: dict) -> dict:
    status_code, result = _client().list_pods(_namespace(query))
    if not 200 <= status_code < 300:
        return _error_result("Pod 列表查询失败", status_code, result)

    pods = [_pod_summary(item) for item in result.get("items", []) or []]
    deployment_name = query.get("deployment_name")
    if deployment_name:
        pods = [pod for pod in pods if str(pod.get("pod_name") or "").startswith(deployment_name)]
    phase = query.get("phase")
    if phase:
        pods = [pod for pod in pods if pod.get("phase") == phase]
    node_name = query.get("node_name")
    if node_name:
        pods = [pod for pod in pods if pod.get("node_name") == node_name]
    return {"is_success": True, "items": pods}


def pod_detail(query: dict) -> dict:
    pod_name = query.get("pod_name", "")
    if not pod_name:
        return {"is_success": False, "msg": "pod_name 不能为空"}

    namespace = _namespace(query)
    status_code, pod = _client().read_pod(namespace, pod_name)
    if status_code == 404:
        return _error_result("Pod 不存在", 404, pod)
    if not 200 <= status_code < 300:
        return _error_result("Pod 详情查询失败", status_code, pod)

    event_status, event_result = _client().list_events(namespace, pod_name)
    events = event_result.get("items", []) if 200 <= event_status < 300 else []
    return {"is_success": True, **_pod_detail(pod, events)}


def pod_logs(query: dict) -> dict:
    pod_name = query.get("pod_name", "")
    if not pod_name:
        return {"is_success": False, "msg": "pod_name 不能为空", "lines": []}

    status_code, result = _client().pod_logs(
        _namespace(query),
        pod_name,
        tail_lines=query.get("tail_lines", 200),
    )
    if not 200 <= status_code < 300:
        return _error_result("Pod 日志查询失败", status_code, result) | {"lines": []}
    raw = result.get("raw", "")
    return {"is_success": True, "lines": raw.splitlines() if raw else []}


def delete_pod(action: dict) -> dict:
    pod_name = action.get("pod_name", "")
    if not pod_name:
        return {"is_success": False, "msg": "pod_name 不能为空"}
    status_code, result = _client().delete_pod(_namespace(action), pod_name)
    if status_code == 404:
        return {"is_success": False, "msg": "Pod 不存在"}
    if not 200 <= status_code < 300:
        return _error_result("Pod 删除失败", status_code, result)
    return {"is_success": True, "pod_name": pod_name}


def restart_pod(action: dict) -> dict:
    result = delete_pod(action)
    if not result.get("is_success"):
        return result
    return {**result, "msg": "Pod 已删除，控制器将自动重建"}
