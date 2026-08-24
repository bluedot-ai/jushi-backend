from urllib.parse import quote_plus


def envelope_field(payload: dict, key: str, default: str = "") -> str:
    return str(payload.get(key) or default)


def response_envelope(
    payload: dict,
    content: dict,
    http_status_code: int = 200,
    msg: str = "OK",
    status: int = 0,
) -> dict:
    # 部署类接口沿用旧服务 envelope，方便前端和历史脚本按 msg_id/serial/context 追踪链路。
    return {
        "msg_id": f"{envelope_field(payload, 'msg_id')}_Resp",
        "head_id": 0,
        "context": envelope_field(payload, "context"),
        "serial": envelope_field(payload, "serial"),
        "version": "1.0.0.1",
        "status": status,
        "content": content,
        "token": "",
        "http_status_code": http_status_code,
        "msg": msg,
        "is_success": 200 <= http_status_code < 300,
    }


def deployment_items(result) -> list:
    # PaaS 列表接口通常把资源放在 items 中；异常结构按空列表处理，避免后续遍历报错。
    if isinstance(result, dict) and isinstance(result.get("items"), list):
        return result["items"]
    return []


def deployment_pod_path(cluster: str, namespace: str, name: str) -> str:
    label_selector = quote_plus(f"app={name}")
    return f"/clusters/{cluster}/namespaces/{namespace}/pods?labelSelector={label_selector}"


def pod_items(result) -> list:
    if isinstance(result, dict) and isinstance(result.get("items"), list):
        return result["items"]
    return []


def service_node_ports(service: dict) -> list[dict]:
    ports = []
    spec = service.get("spec", {}) or {}
    for item in spec.get("ports", []) or []:
        if not isinstance(item, dict) or item.get("nodePort") is None:
            continue
        ports.append({
            "name": item.get("name"),
            "port": item.get("nodePort"),
            "target_port": item.get("targetPort"),
            "protocol": item.get("protocol"),
        })
    return ports


def gpu_resource_limits(deployment: dict) -> dict:
    template_spec = (((deployment.get("spec", {}) or {}).get("template", {}) or {}).get("spec", {}) or {})
    containers = template_spec.get("containers", []) or []
    main_container = containers[0] if containers else {}
    limits = ((main_container.get("resources", {}) or {}).get("limits", {}) or {})
    nested_resources = limits.get("resources", {}) if isinstance(limits.get("resources"), dict) else {}

    resources = {}
    for source in (limits, nested_resources):
        for key, value in source.items():
            if "/" in str(key) and key not in {"cpu", "memory", "storage", "resources"}:
                resources[key] = value
    return resources


def summarize_deployment(deployment: dict) -> dict:
    metadata = deployment.get("metadata", {}) or {}
    annotations = metadata.get("annotations", {}) or {}
    labels = metadata.get("labels", {}) or {}
    spec = deployment.get("spec", {}) or {}
    status = deployment.get("status", {}) or {}
    template_spec = ((spec.get("template", {}) or {}).get("spec", {}) or {})
    containers = template_spec.get("containers", []) or []
    main_container = containers[0] if containers else {}
    resources = main_container.get("resources", {}) or {}

    # 查询接口只返回实例中心需要展示的摘要，避免把 PaaS Deployment 原文整包透出。
    return {
        "name": metadata.get("name"),
        "namespace": metadata.get("namespace"),
        "cluster": metadata.get("cluster"),
        "uid": metadata.get("uid"),
        "created_at": annotations.get("createdAt") or metadata.get("creationTimestamp"),
        "creator": labels.get("creator"),
        "instance_name": labels.get("instance_name"),
        "creator_ip": annotations.get("creatorIp"),
        "deployType": annotations.get("deployType"),
        "workshop_mode": annotations.get("workshopMode") == "true",
        "image": main_container.get("image"),
        "replicas": status.get("replicas", spec.get("replicas", 0)),
        "ready_replicas": status.get("readyReplicas", 0),
        "available_replicas": status.get("availableReplicas", 0),
        "state": status.get("state"),
        "conditions": [
            {
                "type": item.get("type"),
                "status": item.get("status"),
                "reason": item.get("reason"),
                "message": item.get("message"),
            }
            for item in status.get("conditions", []) or []
            if isinstance(item, dict)
        ],
        "resources": {
            "limits": resources.get("limits", {}),
            "requests": resources.get("requests", {}),
        },
        "gpu_resources": gpu_resource_limits(deployment),
    }


def _container_state(container_status: dict) -> str | None:
    state = container_status.get("state") or {}
    if isinstance(state, dict) and state:
        return next(iter(state.keys()))
    return None


def summarize_pod(pod: dict) -> dict:
    metadata = pod.get("metadata", {}) or {}
    status_obj = pod.get("status", {}) or {}
    spec_obj = pod.get("spec", {}) or {}
    container_statuses = status_obj.get("containerStatuses", []) or []

    containers = []
    for container_status in container_statuses:
        containers.append({
            "name": container_status.get("name"),
            "ready": container_status.get("ready"),
            "restart_count": container_status.get("restartCount"),
            "state": _container_state(container_status),
        })

    restart_count = sum(
        int(item.get("restart_count") or 0)
        for item in containers
    )
    ready = bool(containers) and all(item.get("ready") for item in containers)

    return {
        "pod_name": metadata.get("name"),
        "namespace": metadata.get("namespace"),
        "phase": status_obj.get("phase"),
        "node_name": spec_obj.get("nodeName"),
        "pod_ip": status_obj.get("podIP"),
        "host_ip": status_obj.get("hostIP"),
        "ip": status_obj.get("podIP"),
        "restart_count": restart_count,
        "ready": ready,
        "created_at": metadata.get("creationTimestamp") or status_obj.get("startTime"),
        "start_time": status_obj.get("startTime"),
        "containers": containers,
    }


def summarize_pods(pods: list[dict]) -> dict:
    return {
        "total_pods": len(pods),
        "running_pods": sum(1 for pod in pods if pod.get("phase") == "Running"),
        "ready_pods": sum(1 for pod in pods if pod.get("ready")),
    }
