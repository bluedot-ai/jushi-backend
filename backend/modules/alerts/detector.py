try:
    from backend.config import Config
    from backend.modules.deploy.repository import list_deploy_instances
    from backend.services.k8s_client import K8sClient
except ModuleNotFoundError:
    from config import Config
    from modules.deploy.repository import list_deploy_instances
    from services.k8s_client import K8sClient


IMAGE_PULL_REASONS = {"ImagePullBackOff", "ErrImagePull", "InvalidImageName"}
START_FAILED_REASONS = {"CrashLoopBackOff", "CreateContainerConfigError", "CreateContainerError", "RunContainerError"}
RESOURCE_MESSAGES = ("Insufficient nvidia.com/gpu", "Insufficient huawei.com/Ascend", "Insufficient cpu", "Insufficient memory")


def detect_cluster_alerts(query: dict | None = None) -> tuple[list[dict], dict | None, dict]:
    query = query or {}
    scope = query.get("scope") or "cluster"
    namespace = query.get("namespace") or Config.DCE_NAMESPACE
    cluster_name = query.get("cluster_name") or Config.DCE_CLUSTER

    client = K8sClient.from_config(Config)
    if scope == "namespace":
        pod_status, pod_result = client.list_pods(namespace)
        event_status, event_result = client.list_events(namespace)
        node_status, node_result = client.list_nodes()
        scan_scope = {"scope": "namespace", "namespace": namespace, "cluster_name": cluster_name}
    else:
        pod_status, pod_result = client.list_cluster_pods()
        event_status, event_result = client.list_cluster_events()
        node_status, node_result = client.list_nodes()
        scan_scope = {"scope": "cluster", "namespace": "all", "cluster_name": cluster_name}

    errors = []
    if not 200 <= pod_status < 300:
        errors.append(_scan_error("pods", pod_status, pod_result, scan_scope))
    if not 200 <= event_status < 300:
        errors.append(_scan_error("events", event_status, event_result, scan_scope))
    if not 200 <= node_status < 300:
        errors.append(_scan_error("nodes", node_status, node_result, scan_scope))

    if scope == "cluster" and _is_forbidden(pod_status, event_status):
        fallback_namespace = namespace or Config.DCE_NAMESPACE
        fallback_pod_status, fallback_pod_result = client.list_pods(fallback_namespace)
        fallback_event_status, fallback_event_result = client.list_events(fallback_namespace)
        if 200 <= fallback_pod_status < 300:
            pod_status, pod_result = fallback_pod_status, fallback_pod_result
            event_status, event_result = fallback_event_status, fallback_event_result
            scan_scope = {
                "scope": "namespace",
                "requested_scope": "cluster",
                "namespace": fallback_namespace,
                "cluster_name": cluster_name,
                "fallback_reason": "cluster-scope RBAC denied; scanned namespace scope instead",
            }
            if not 200 <= event_status < 300:
                errors.append(_scan_error("events", event_status, event_result, scan_scope))
        else:
            errors.append(_scan_error("pods", fallback_pod_status, fallback_pod_result, {
                "scope": "namespace",
                "namespace": fallback_namespace,
                "cluster_name": cluster_name,
            }))

    if not 200 <= pod_status < 300:
        return [], {"errors": errors}, {**scan_scope, "pod_count": 0, "event_count": 0, "node_count": 0}

    pods = pod_result.get("items", []) or []
    events = event_result.get("items", []) if 200 <= event_status < 300 else []
    nodes = node_result.get("items", []) if 200 <= node_status < 300 else []
    events_by_pod = _events_by_kind_and_name(events, "Pod")

    records = {}
    try:
        records = {
            row.get("deployment_name"): row
            for row in list_deploy_instances()
            if row.get("deployment_name")
        }
    except Exception as exc:
        errors.append({"source": "deploy_instances", "error": str(exc)})

    alerts = []
    for pod in pods:
        pod_namespace = (pod.get("metadata") or {}).get("namespace") or namespace
        alerts.extend(_detect_pod_alerts(cluster_name, pod_namespace, pod, events_by_pod, records))

    alerts.extend(_detect_warning_event_alerts(cluster_name, events))
    alerts.extend(_detect_node_alerts(cluster_name, nodes, _events_by_kind_and_name(events, "Node")))

    diagnostics = {
        **scan_scope,
        "pod_count": len(pods),
        "event_count": len(events),
        "node_count": len(nodes),
        "sources": ["k8s_pods", "k8s_events", "k8s_nodes"],
    }
    return alerts, {"errors": errors} if errors else None, diagnostics


def detect_algorithm_alerts() -> tuple[list[dict], dict | None]:
    alerts, scan_error, _diagnostics = detect_cluster_alerts({"scope": "namespace", "namespace": "algorithm"})
    return alerts, scan_error


def _scan_error(source: str, status: int, response: dict, scan_scope: dict) -> dict:
    item = {"source": source, "status": status, "response": response}
    if status == 403:
        scope = scan_scope.get("scope") or "cluster"
        item["permission_required"] = {
            "api_group": "",
            "resource": source,
            "verb": "list",
            "scope": "cluster" if scope == "cluster" else "namespace",
            "namespace": None if scope == "cluster" else scan_scope.get("namespace"),
            "service_account": "system:serviceaccount:algorithm:jushi-deploy-api",
        }
        if scope == "cluster":
            item["hint"] = (
                "Cluster-wide alerts require a ClusterRole/ClusterRoleBinding that grants list on pods, events, and nodes."
            )
    return item


def _is_forbidden(*statuses: int) -> bool:
    return any(status == 403 for status in statuses)


def _events_by_kind_and_name(events: list[dict], kind: str) -> dict:
    grouped = {}
    for event in events:
        involved = event.get("involvedObject") or {}
        if involved.get("kind") != kind:
            continue
        namespace = involved.get("namespace") or (event.get("metadata") or {}).get("namespace") or ""
        name = involved.get("name") or ""
        if name:
            grouped.setdefault((namespace, name), []).append(event)
    return grouped


def _detect_pod_alerts(cluster_name: str, namespace: str, pod: dict, events_by_pod: dict, records: dict) -> list[dict]:
    meta = pod.get("metadata") or {}
    status = pod.get("status") or {}
    labels = meta.get("labels") or {}
    pod_name = meta.get("name") or ""
    deployment_name = labels.get("app") or _deployment_from_pod_name(pod_name)
    record = records.get(deployment_name, {})
    instance_name = record.get("instance_name") or deployment_name or pod_name
    created_at = record.get("created_at") or meta.get("creationTimestamp")
    events = events_by_pod.get((namespace, pod_name), [])

    context = {
        "cluster_name": cluster_name,
        "namespace": namespace,
        "pod_name": pod_name,
        "deployment_name": deployment_name,
        "instance_name": instance_name,
        "created_at": created_at,
        "node_name": (pod.get("spec") or {}).get("nodeName"),
        "phase": status.get("phase"),
    }

    detected = []
    phase = status.get("phase")
    if phase == "Pending":
        message = _event_message(events) or "Pod is Pending and the workload is not available."
        level = "high" if _has_resource_shortage(message) else "medium"
        title = "GPU resource insufficient" if _has_resource_shortage(message) else "Pod pending"
        detected.append(_alert(context, "pod_pending", level, title, message, events))
    elif phase == "Failed":
        detected.append(_alert(context, "pod_failed", "high", "Pod failed", "Pod entered Failed phase.", events))
    elif phase == "Unknown":
        detected.append(_alert(context, "pod_unknown", "medium", "Pod status unknown", "Pod phase is Unknown.", events))

    for container in status.get("containerStatuses", []) or []:
        state = container.get("state") or {}
        waiting = state.get("waiting") or {}
        terminated = state.get("terminated") or {}
        reason = waiting.get("reason") or terminated.get("reason")
        if reason in IMAGE_PULL_REASONS:
            detected.append(
                _alert(
                    context,
                    "image_pull_failed",
                    "high",
                    "Image pull failed",
                    waiting.get("message") or _event_message(events) or "Container image cannot be pulled.",
                    events,
                    container.get("name"),
                )
            )
        elif reason in START_FAILED_REASONS:
            detected.append(
                _alert(
                    context,
                    "container_start_failed",
                    "high",
                    "Container start failed",
                    waiting.get("message") or _event_message(events) or "Container failed to start.",
                    events,
                    container.get("name"),
                )
            )
        elif reason == "OOMKilled":
            detected.append(
                _alert(
                    context,
                    "oom_killed",
                    "high",
                    "Container OOMKilled",
                    terminated.get("message") or "Container was terminated because it exceeded memory limits.",
                    events,
                    container.get("name"),
                )
            )
    return detected


def _detect_warning_event_alerts(cluster_name: str, events: list[dict]) -> list[dict]:
    alerts = []
    for event in events:
        if event.get("type") != "Warning":
            continue
        involved = event.get("involvedObject") or {}
        kind = involved.get("kind") or "Object"
        name = involved.get("name") or (event.get("metadata") or {}).get("name")
        namespace = involved.get("namespace") or (event.get("metadata") or {}).get("namespace") or "cluster"
        reason = event.get("reason") or "Warning"
        deployment_name = _deployment_from_pod_name(name) if kind == "Pod" else ""
        context = {
            "cluster_name": cluster_name,
            "namespace": namespace,
            "pod_name": name if kind == "Pod" else "",
            "deployment_name": deployment_name,
            "instance_name": deployment_name or name,
            "node_name": name if kind == "Node" else "",
            "kind": kind,
            "reason": reason,
        }
        alerts.append(
            _alert(
                context,
                f"k8s_event_{reason}".lower(),
                _event_level(reason, event.get("message") or ""),
                f"{kind} warning: {reason}",
                event.get("message") or reason,
                [event],
            )
        )
    return alerts


def _detect_node_alerts(cluster_name: str, nodes: list[dict], events_by_node: dict) -> list[dict]:
    alerts = []
    for node in nodes:
        meta = node.get("metadata") or {}
        status = node.get("status") or {}
        node_name = meta.get("name") or ""
        conditions = status.get("conditions") or []
        node_events = events_by_node.get(("", node_name), []) + events_by_node.get(("default", node_name), [])
        for condition in conditions:
            condition_type = condition.get("type")
            condition_status = condition.get("status")
            if condition_type == "Ready" and condition_status != "True":
                context = _node_context(cluster_name, node_name, condition)
                alerts.append(_alert(context, "node_not_ready", "high", "Node not ready", condition.get("message") or "Node is not Ready.", node_events))
            elif condition_type in {"MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable"} and condition_status == "True":
                context = _node_context(cluster_name, node_name, condition)
                alerts.append(_alert(context, f"node_{condition_type}".lower(), "high", f"Node {condition_type}", condition.get("message") or condition_type, node_events))
    return alerts


def _node_context(cluster_name: str, node_name: str, condition: dict) -> dict:
    return {
        "cluster_name": cluster_name,
        "namespace": "cluster",
        "pod_name": "",
        "deployment_name": "",
        "instance_name": node_name,
        "node_name": node_name,
        "phase": condition.get("type"),
    }


def _alert(
    context: dict,
    alert_type: str,
    level: str,
    title: str,
    message: str,
    events: list[dict],
    container_name: str | None = None,
) -> dict:
    namespace = context.get("namespace") or "cluster"
    target_name = context.get("pod_name") or context.get("node_name") or context.get("instance_name")
    fingerprint_parts = [
        context.get("cluster_name") or Config.DCE_CLUSTER,
        namespace,
        context.get("deployment_name") or target_name or "",
        alert_type,
        container_name or context.get("reason") or "",
    ]
    return {
        "cluster_name": context.get("cluster_name") or Config.DCE_CLUSTER,
        "namespace": namespace,
        "alert_type": alert_type,
        "alert_level": level,
        "title": title,
        "message": message,
        "source": "k8s",
        "target_name": target_name,
        "instance_name": context.get("instance_name") or target_name,
        "deployment_name": context.get("deployment_name"),
        "fingerprint": ":".join(fingerprint_parts),
        "evidence": {
            **context,
            "container_name": container_name,
            "events": [_event_snapshot(event) for event in events[:5]],
        },
    }


def _deployment_from_pod_name(pod_name: str) -> str:
    parts = pod_name.rsplit("-", 2)
    if len(parts) >= 3:
        return parts[0]
    return pod_name


def _event_message(events: list[dict]) -> str:
    if not events:
        return ""
    latest = sorted(events, key=lambda item: item.get("lastTimestamp") or item.get("eventTime") or "", reverse=True)[0]
    return latest.get("message") or latest.get("reason") or ""


def _event_snapshot(event: dict) -> dict:
    involved = event.get("involvedObject") or {}
    return {
        "namespace": involved.get("namespace") or (event.get("metadata") or {}).get("namespace"),
        "kind": involved.get("kind"),
        "name": involved.get("name"),
        "type": event.get("type"),
        "reason": event.get("reason"),
        "message": event.get("message"),
        "last_timestamp": event.get("lastTimestamp") or event.get("eventTime"),
    }


def _event_level(reason: str, message: str) -> str:
    text = f"{reason} {message}"
    if _has_resource_shortage(text) or reason in IMAGE_PULL_REASONS or reason in START_FAILED_REASONS:
        return "high"
    if reason in {"Failed", "FailedScheduling", "Unhealthy", "BackOff", "Killing"}:
        return "high"
    return "medium"


def _has_resource_shortage(message: str) -> bool:
    return any(item in (message or "") for item in RESOURCE_MESSAGES)
