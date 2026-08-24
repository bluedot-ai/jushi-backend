def build_deploy_record(
    name: str,
    payload: dict,
    *,
    gpu_vendor: str = "",
    node_ports=None,
    log_path: str | None = None,
    status: str = "running",
) -> dict:
    # 构建部署实例记录，写入 deploy_instance 表。
    content = payload.get("content", {}) or {}
    devices = content.get("devices", {}) or {}
    gpu_type = next(iter(devices.keys()), "")
    return {
        "instance_name": content.get("instance_name") or content.get("name") or name,
        "deployment_name": name,
        "gpu_vendor": gpu_vendor,
        "gpu_type": gpu_type,
        "gpu_count": devices.get(gpu_type, 0) if gpu_type else 0,
        "deploy_type": content.get("deployType", ""),
        "creator": content.get("creator", ""),
        "status": status,
        "node_ports": node_ports,
        "log_path": log_path,
    }
