def normalize_alert_query(payload: dict) -> dict:
    if not payload:
        return {}
    content = payload.get("content") or {}
    source = content if content else payload
    scope = source.get("scope") or "cluster"
    namespace = source.get("namespace")
    if namespace and namespace != "all":
        scope = source.get("scope") or "namespace"
    return {
        "scope": scope,
        "cluster_name": source.get("cluster_name"),
        "namespace": namespace,
        "level": source.get("level", "all"),
        "limit": source.get("limit", 20),
        "page": source.get("page", 1),
        "page_size": source.get("page_size") or source.get("limit"),
        "status": source.get("status"),
        "deployment_name": source.get("deployment_name"),
    }


def normalize_alert_history_query(payload: dict) -> dict:
    query = normalize_alert_query(payload)
    status = query.get("status")
    if status in {"resolved", "ignored"}:
        query["statuses"] = [status]
    else:
        query["statuses"] = ["resolved", "ignored"]
    return query


def normalize_alert_action(payload: dict) -> dict:
    if not payload:
        return {}
    content = payload.get("content") or {}
    return {
        "id": content.get("id") or payload.get("id"),
        "resolver": content.get("resolver") or payload.get("resolver", ""),
    }


def normalize_alert_create(payload: dict) -> dict:
    if not payload:
        return {}
    content = payload.get("content") or {}
    source = content if content else payload
    return {
        "alert_type": source.get("alert_type", ""),
        "alert_level": source.get("alert_level", "low"),
        "title": source.get("title", ""),
        "message": source.get("message", ""),
        "source": source.get("source", ""),
        "target_name": source.get("target_name", ""),
        "cluster_name": source.get("cluster_name"),
        "namespace": source.get("namespace"),
        "instance_name": source.get("instance_name"),
        "deployment_name": source.get("deployment_name"),
        "fingerprint": source.get("fingerprint"),
        "evidence": source.get("evidence"),
        "status": source.get("status") or "open",
    }
