import json
import os
import random
import re
import socket
import time
import uuid

from flask import g, request

from .helpers import (
    deployment_items as _deployment_items,
    deployment_pod_path,
    gpu_resource_limits,
    pod_items,
    response_envelope as _response_envelope,
    service_node_ports,
    summarize_deployment,
    summarize_pod,
    summarize_pods,
)
from . import repository
from .model import build_deploy_record
from .schema import get_deploy_name, parse_optional_subport, validate_create_payload, validate_deploy_envelope

try:
    from backend.config import Config
    from backend.services.paas_client import PaasClient
    from backend.services.k8s_client import K8sClient
    from backend.modules.ports.repository import resolve_blocked_ports
except ModuleNotFoundError:
    from config import Config
    from services.paas_client import PaasClient
    from services.k8s_client import K8sClient
    from modules.ports.repository import resolve_blocked_ports


MIN_CPU_M = 2000
MIN_MEM_BYTES = 4 * 1024 ** 3
NODEPORT_START = 30000
NODEPORT_END = 59999
NODEPORT_MAX_ATTEMPTS = int(os.getenv("NODEPORT_MAX_ATTEMPTS", "300"))
DEPLOYMENT_LIST_PAGE_SIZE = int(os.getenv("DEPLOYMENT_LIST_PAGE_SIZE", "200"))

NVIDIA_IMAGE = os.getenv(
    "NVIDIA_IMAGE",
    "nvidia/cuda:11.6.2-cudnn8-devel-ubuntu20.04_v1",
)
ALGORITHM_PACKAGE_HOST_DIR = os.getenv("ALGORITHM_PACKAGE_HOST_DIR", "/opt")
NVIDIA_PACKAGE_NAME = os.getenv("NVIDIA_PACKAGE_NAME", "mtworkflow_x86.zip")
NVIDIA_WORKDIR = os.getenv("NVIDIA_WORKDIR", "mtworkflow_x86")

WORKSHOP_MODE_ENABLED = os.getenv("WORKSHOP_MODE_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
WORKSHOP_CLIENT_IPS = {
    item.strip()
    for item in os.getenv("WORKSHOP_CLIENT_IPS", "10.9.100.195").split(",")
    if item.strip()
}
WORKSHOP_PORT_8018 = int(os.getenv("WORKSHOP_PORT_8018", " 10001"))
WORKSHOP_PORT_8019 = int(os.getenv("WORKSHOP_PORT_8019", "10002"))

SHARED_DATA_ENABLED = os.getenv("SHARED_DATA_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
SHARED_DATA_HOST_PATH = os.getenv("SHARED_DATA_HOST_PATH", "/disks/sda/jx5000/")
SHARED_DATA_MOUNT_PATH = os.getenv("SHARED_DATA_MOUNT_PATH", "/root/ADCShared/")

GPU_DEVICE_MAP = {
    "NVIDIA/GPU": {
        "resource_name": "nvidia.com/gpu",
        "deploy_type": "NvidiaInfer",
        "vendor": "NVIDIA",
    },
    "Huawei/Ascend310P": {
        "resource_name": "huawei.com/Ascend310P",
        "deploy_type": "HuaweiInfer",
        "vendor": "Huawei",
    },
}


def _failed_check(key: str, label: str, display: str, message: str, detail=None) -> dict:
    result = {
        "key": key,
        "label": label,
        "status": "failed",
        "display": display,
        "message": message,
    }
    if detail is not None:
        result["detail"] = detail
    return result


def _passed_check(key: str, label: str, display: str = "通过", detail=None) -> dict:
    result = {
        "key": key,
        "label": label,
        "status": "passed",
        "display": display,
    }
    if detail is not None:
        result["detail"] = detail
    return result


def _parse_cpu_m(value) -> int:
    # Kubernetes/PaaS CPU 可能返回 "2500m" 或 "2.5"，统一换算成毫核 m。
    if value is None:
        return 0
    text = str(value).strip()
    if not text:
        return 0
    if text.endswith("m"):
        return int(float(text[:-1] or 0))
    return int(float(text) * 1000)


def _parse_memory_bytes(value) -> int:
    # Kubernetes/PaaS 内存可能返回 Gi/Mi 等单位，预检统一换算成 bytes 后比较。
    if value is None:
        return 0
    text = str(value).strip()
    if not text:
        return 0

    units = {
        "Ki": 1024,
        "Mi": 1024 ** 2,
        "Gi": 1024 ** 3,
        "Ti": 1024 ** 4,
        "K": 1000,
        "M": 1000 ** 2,
        "G": 1000 ** 3,
        "T": 1000 ** 4,
    }
    for suffix, multiplier in units.items():
        if text.endswith(suffix):
            return int(float(text[: -len(suffix)] or 0) * multiplier)
    return int(float(text))


def _parse_int_quantity(value) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _extract_device_request(payload: dict) -> tuple[dict | None, str | None]:
    # 资源预检只处理一种 GPU 类型，避免一次请求同时混用 NVIDIA 和 Huawei 导致模板选择不确定。
    content = payload.get("content", {}) or {}
    devices = content.get("devices")
    if not isinstance(devices, dict) or not devices:
        return None, "缺少必填字段：content.devices"

    if len(devices) != 1:
        return None, "一次预检只支持一种 GPU 类型"

    device_key, requested = next(iter(devices.items()))
    if device_key not in GPU_DEVICE_MAP:
        return None, f"不支持的 GPU 类型：{device_key}"

    requested_count = _parse_int_quantity(requested)
    if requested_count <= 0:
        return None, "GPU 数量必须大于 0"

    profile = GPU_DEVICE_MAP[device_key]
    deploy_type = str(content.get("deployType") or "").strip()
    if deploy_type and deploy_type != profile["deploy_type"]:
        return None, f"{device_key} 必须匹配 deployType={profile['deploy_type']}"

    gpu_resource_name = str(payload.get("gpu_resource_name") or "").strip()
    if gpu_resource_name and gpu_resource_name != profile["resource_name"]:
        return None, f"{device_key} 必须匹配 gpu_resource_name={profile['resource_name']}"

    return {
        "device_key": device_key,
        "requested": requested_count,
        **profile,
    }, None


def _existing_node_ports(services_result) -> set[int]:
    # 从已有 Service 中提取 nodePort，后续随机端口必须避开这些已经被集群占用的端口。
    ports = set()
    if not isinstance(services_result, dict):
        return ports
    for service in services_result.get("items", []) or []:
        for port_obj in (service.get("spec", {}) or {}).get("ports", []) or []:
            node_port = port_obj.get("nodePort")
            if isinstance(node_port, int):
                ports.add(node_port)
    return ports


def _deployment_exists(deployments: list, name: str) -> bool:
    # 预检阶段只做同名检测，不加锁；真正创建时仍需要再检查一次，避免并发窗口。
    if not name:
        return False
    for item in deployments:
        metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
        if metadata.get("name") == name:
            return True
    return False


def _resource_value(resources: dict, resource_name: str) -> int:
    if not isinstance(resources, dict):
        return 0
    return _parse_int_quantity(resources.get(resource_name))


def _node_name(node: dict) -> str:
    metadata = node.get("metadata", {}) or {}
    return str(metadata.get("name") or node.get("name") or "").strip()


def _node_raw_allocatable(node: dict) -> dict:
    status = node.get("status", {}) or {}
    summary = status.get("resourceSummary", {}) or {}
    return (
        summary.get("allocatable")
        or status.get("allocatable")
        or status.get("capacity")
        or {}
    )


def _pod_resource_request(pod: dict, resource_name: str) -> int:
    total = 0
    spec = pod.get("spec", {}) or {}
    for container in spec.get("containers", []) or []:
        resources = container.get("resources", {}) or {}
        limits = resources.get("limits", {}) or {}
        requests = resources.get("requests", {}) or {}
        total += max(
            _resource_value(limits, resource_name),
            _resource_value(requests, resource_name),
        )
    return total


def _is_active_scheduled_pod(pod: dict) -> bool:
    metadata = pod.get("metadata", {}) or {}
    if metadata.get("deletionTimestamp"):
        return False
    phase = ((pod.get("status", {}) or {}).get("phase") or "").strip()
    if phase in {"Succeeded", "Failed"}:
        return False
    return bool((pod.get("spec", {}) or {}).get("nodeName"))


def _node_resource_usage_from_paas(client: PaasClient, resource_name: str) -> tuple[dict | None, dict | None]:
    node_path = f"/clusters/{Config.DCE_CLUSTER}/nodes"
    node_status, node_result = client.request_with_status("GET", node_path)
    if node_status != 200:
        return None, {"nodes": node_result, "http_status_code": node_status}

    pod_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/pods"
    pod_status, pod_result = client.request_with_status("GET", pod_path)
    if pod_status != 200:
        return None, {"pods": pod_result, "http_status_code": pod_status}

    nodes = [node for node in _deployment_items(node_result) if isinstance(node, dict)]
    pods = [pod for pod in pod_items(pod_result) if isinstance(pod, dict) and _is_active_scheduled_pod(pod)]

    by_node = {}
    for node in nodes:
        name = _node_name(node)
        if not name:
            continue
        total = _resource_value(_node_raw_allocatable(node), resource_name)
        by_node[name] = {"total": total, "used": 0, "available": total}

    for pod in pods:
        node_name = str(((pod.get("spec", {}) or {}).get("nodeName")) or "").strip()
        if node_name not in by_node:
            continue
        requested = _pod_resource_request(pod, resource_name)
        if requested <= 0:
            continue
        by_node[node_name]["used"] += requested

    total = 0
    used = 0
    max_available = 0
    node_details = []
    for name, item in by_node.items():
        item["available"] = max(item["total"] - item["used"], 0)
        total += item["total"]
        used += item["used"]
        max_available = max(max_available, item["available"])
        node_details.append({
            "node_name": name,
            "total": item["total"],
            "used": item["used"],
            "available": item["available"],
        })

    if total <= 0:
        return None, {"error": f"节点未暴露 {resource_name} 可调度资源"}

    return {
        "total": total,
        "used": used,
        "available": max_available,
        "total_available": sum(item["available"] for item in by_node.values()),
        "nodes": sorted(node_details, key=lambda item: item["node_name"]),
    }, None


def _resource_nodes_service():
    try:
        from backend.modules.resources.service import nodes as resource_nodes
    except ModuleNotFoundError:
        from modules.resources.service import nodes as resource_nodes
    return resource_nodes


def _node_resource_usage_from_resource_nodes(resource_name: str) -> tuple[dict | None, dict | None]:
    if resource_name not in {"nvidia.com/gpu", "nvidia.com/vgpu"}:
        return None, {"error": f"资源节点明细暂未支持 {resource_name} 预检"}

    try:
        result = _resource_nodes_service()({"namespace": Config.DCE_NAMESPACE})
    except Exception as exc:
        return None, {"error": str(exc)}

    if not isinstance(result, dict) or not result.get("is_success"):
        return None, {"response": result}

    items = result.get("items") or []
    total = 0
    used = 0
    max_available = 0
    total_available = 0
    node_details = []

    for item in items:
        if not isinstance(item, dict):
            continue

        gpu_mode = str(item.get("gpu_mode") or "").lower()
        if resource_name == "nvidia.com/gpu" and gpu_mode != "gpu":
            continue

        if resource_name == "nvidia.com/vgpu":
            node_total = _parse_int_quantity(item.get("vgpu_total"))
            node_used = _parse_int_quantity(item.get("vgpu_used"))
            node_available = _parse_int_quantity(item.get("vgpu_available"))
        else:
            node_total = _parse_int_quantity(item.get("physical_gpu_total"))
            node_used = _parse_int_quantity(item.get("physical_gpu_used"))
            node_available = _parse_int_quantity(item.get("physical_gpu_available"))

        if node_total <= 0:
            continue

        total += node_total
        used += node_used
        max_available = max(max_available, node_available)
        total_available += node_available
        node_details.append({
            "node_name": item.get("node_name"),
            "gpu_mode": item.get("gpu_mode"),
            "total": node_total,
            "used": node_used,
            "available": node_available,
            "source": "resources_nodes",
        })

    if total <= 0:
        return None, {"error": f"资源节点明细未暴露 {resource_name} 可调度资源"}

    return {
        "total": total,
        "used": used,
        "available": max_available,
        "total_available": total_available,
        "nodes": sorted(node_details, key=lambda item: item.get("node_name") or ""),
    }, None


def _get_client_ip() -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.headers.get("X-Real-IP", "").strip() or (request.remote_addr or "")


def _safe_shell_value(value: str) -> str:
    # subip 会写入 initContainer 的 sed 命令，只允许 IP/主机名常见字符。
    value = str(value or "").strip()
    return value if re.fullmatch(r"[0-9A-Za-z_.:-]+", value) else "unknown"


def _safe_label_value(value: str, default: str = "unknown") -> str:
    value = re.sub(r"[^0-9A-Za-z_.-]+", "-", str(value or "").strip())[:63].strip(".-_")
    return value or default


def _current_creator(payload: dict) -> str:
    content = payload.get("content", {}) or {}
    current_user = getattr(g, "current_user", {}) or {}
    return str(
        content.get("creator")
        or current_user.get("username")
        or request.headers.get("X-User")
        or request.headers.get("X-Forwarded-User")
        or "unknown"
    ).strip()


def _is_workshop_request(client_ip: str) -> bool:
    return WORKSHOP_MODE_ENABLED and client_ip in WORKSHOP_CLIENT_IPS


def _precheck_passed(payload: dict, *, ignore_nodeport: bool = False) -> tuple[bool, dict, int]:
    result = check_available(payload, validate_envelope=False)
    content = result.get("content", {}) if isinstance(result, dict) else {}
    failed_checks = [
        check for check in content.get("checks", []) or []
        if check.get("status") == "failed" and not (ignore_nodeport and check.get("key") == "nodeport")
    ]
    if content.get("can_create") and not failed_checks:
        return True, result, 200
    if ignore_nodeport and not failed_checks and content.get("checks"):
        content = {**content, "can_create": True, "reason": "资源预检通过"}
        return True, {**result, "content": content, "status": 0, "http_status_code": 200, "is_success": True}, 200
    return False, result, result.get("http_status_code", 400) if isinstance(result, dict) else 400


def _occupied_node_ports(client: PaasClient) -> tuple[set[int], dict | None, int]:
    path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/services"
    status, result = client.request_with_status("GET", path)
    if status != 200:
        return set(), result if isinstance(result, dict) else {"response": result}, status
    return _existing_node_ports(result), None, status


def _is_port_locally_free(port: int) -> bool:
    # 只能作为 API 容器所在环境的补充检查，真正集群占用仍以 PaaS Service 为准。
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def _select_subport(client: PaasClient) -> tuple[int | None, dict | None, int]:
    service_ports, service_error, service_status = _occupied_node_ports(client)
    if service_error is not None:
        return None, service_error, 502 if service_status != 504 else 504

    try:
        blocked_ports = set(resolve_blocked_ports().get("blocked_ports", []))
    except Exception as exc:
        return None, {"error": str(exc)}, 503

    occupied = {
        port for port in service_ports.union(blocked_ports)
        if NODEPORT_START <= port <= NODEPORT_END
    }
    for _ in range(NODEPORT_MAX_ATTEMPTS):
        port = random.randint(NODEPORT_START, NODEPORT_END)
        if port in occupied:
            continue
        if _is_port_locally_free(port):
            return port, None, 200

    return None, {"error": f"No free port found in range {NODEPORT_START}-{NODEPORT_END}"}, 409


def _service_nodeports_with_retry(client: PaasClient, name: str, retries: int = 10, sleep_s: float = 0.3) -> list[dict]:
    path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/services/{name}"
    for _ in range(retries):
        status, result = client.request_with_status("GET", path)
        if status == 200 and isinstance(result, dict):
            ports = (result.get("spec", {}) or {}).get("ports", []) or []
            node_ports = [
                {"name": item.get("name", ""), "port": item.get("nodePort")}
                for item in ports
                if isinstance(item, dict) and item.get("nodePort") is not None
            ]
            if node_ports:
                return node_ports
        time.sleep(sleep_s)
    return []


def _build_deployment(
    *,
    name: str,
    instance_name: str,
    client_ip: str,
    deploy_type: str,
    device_request: dict,
    subport: int,
    workshop_mode: bool,
) -> dict:
    safe_instance_name = _safe_label_value(instance_name or name)
    safe_client_ip = _safe_shell_value(client_ip)
    alias_name = str(instance_name or name).strip()
    created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    gpu_count = str(device_request["requested"])
    resource_name = device_request["resource_name"]

    container_ports = [{"containerPort": 8018, "protocol": "TCP"}]
    if workshop_mode:
        container_ports[0]["hostPort"] = WORKSHOP_PORT_8018

    volume_mounts = [
        {"mountPath": "/workspace/Alg/", "name": "volume-alg"},
        {"mountPath": "/dev/shm", "name": "volume-memory"},
    ]
    volumes = [
        {"emptyDir": {}, "name": "volume-alg"},
        {"hostPath": {"path": ALGORITHM_PACKAGE_HOST_DIR, "type": "Directory"}, "name": "volume-zip"},
        {"emptyDir": {"medium": "Memory", "sizeLimit": "16Gi"}, "name": "volume-memory"},
    ]
    if SHARED_DATA_ENABLED:
        volume_mounts.append({"mountPath": SHARED_DATA_MOUNT_PATH, "name": "volume-shared-data"})
        volumes.append({"hostPath": {"path": SHARED_DATA_HOST_PATH, "type": "DirectoryOrCreate"}, "name": "volume-shared-data"})

    init_command = (
        f"cp /zip/{NVIDIA_PACKAGE_NAME} /workspace/Alg/ && "
        f"unzip -o /workspace/Alg/{NVIDIA_PACKAGE_NAME} -d /workspace/Alg/ && "
        f"sed -i '88s/\\\"subip\\\": *\\\"[^\\\"]*\\\"/\\\"subip\\\":\\\"{safe_client_ip}\\\"/;"
        f"89s/\\\"subport\\\": *[0-9]\\+/\\\"subport\\\":{subport}/' "
        f"/workspace/Alg/{NVIDIA_WORKDIR}/cfg/runmode.cfg"
    )

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": Config.DCE_NAMESPACE,
            "labels": {"app": name, "instance_name": safe_instance_name},
            "annotations": {
                "kpanda.io/alias-name": f"{alias_name}/{client_ip}" if client_ip else alias_name,
                "createdAt": created_at,
                "creatorIp": client_ip,
                "deployType": deploy_type,
                "workshopMode": "true" if workshop_mode else "false",
            },
        },
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name, "instance_name": safe_instance_name}},
                "spec": {
                    "initContainers": [{
                        "name": "init-copy-unzip",
                        "image": "busybox",
                        "imagePullPolicy": "IfNotPresent",
                        "command": ["sh", "-c"],
                        "args": [init_command],
                        "volumeMounts": [
                            {"name": "volume-alg", "mountPath": "/workspace/Alg/"},
                            {"name": "volume-zip", "mountPath": "/zip"},
                        ],
                    }],
                    "containers": [{
                        "name": name,
                        "image": NVIDIA_IMAGE,
                        "imagePullPolicy": "IfNotPresent",
                        "command": ["sh", "-c"],
                        "args": [f"cd /workspace/Alg/{NVIDIA_WORKDIR}/; chmod +x mtworkflow*; stdbuf -o0 sh mtworkflow.sh;"],
                        "ports": container_ports,
                        "resources": {
                            "limits": {"cpu": "8", "memory": "16Gi", resource_name: gpu_count},
                            "requests": {"cpu": "1", "memory": "2Gi", resource_name: gpu_count},
                        },
                        "volumeMounts": volume_mounts,
                    }],
                    "volumes": volumes,
                },
            },
        },
    }


def _build_service(*, name: str, instance_name: str, client_ip: str, deploy_type: str) -> dict:
    created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    safe_instance_name = _safe_label_value(instance_name or name)
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": Config.DCE_NAMESPACE,
            "labels": {"app": name, "instance_name": safe_instance_name},
            "annotations": {
                "createdAt": created_at,
                "creatorIp": client_ip,
                "deployType": deploy_type,
                "workshopMode": "false",
            },
        },
        "spec": {
            "type": "NodePort",
            "selector": {"app": name},
            "ports": [{"name": "tcp-8018", "port": 8018, "targetPort": 8018, "protocol": "TCP"}],
        },
    }


def _paas_json_payload(kind: str, data: dict) -> dict:
    payload = {
        "cluster": Config.DCE_CLUSTER,
        "namespace": Config.DCE_NAMESPACE,
        "data": json.dumps(data, separators=(",", ":"), ensure_ascii=False),
    }
    if kind:
        payload["kind"] = kind
    return payload


def _rollback_created_resources(client: PaasClient, name: str, *, service_created: bool) -> None:
    if service_created:
        service_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/services/{name}"
        client.request_with_status("DELETE", service_path)
    deploy_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/deployments/{name}"
    client.request_with_status("DELETE", deploy_path)


def check_available(payload: dict, *, validate_envelope: bool = True) -> dict:
    if validate_envelope:
        valid, message = validate_deploy_envelope(payload, "check")
        if not valid:
            return _response_envelope(payload, {"error": message}, 400, message, -1)

    # 资源预检只判断"当前配置是否具备创建条件"，不会创建 Deployment、Service 或占用端口。
    device_request, error = _extract_device_request(payload)
    if error:
        content = {
            "can_create": False,
            "reason": error,
            "checks": [
                _failed_check(
                    "gpu_available",
                    "GPU 可用余量",
                    "未通过",
                    error,
                )
            ],
            "devices": (payload.get("content", {}) or {}).get("devices", {}),
        }
        return _response_envelope(payload, content, 400, error, -1)

    if not Config.DCE_API_BASE:
        msg = "PaaS 地址未配置"
        return _response_envelope(payload, {"can_create": False, "reason": msg, "checks": []}, 500, msg, -1)
    if not Config.DCE_TOKEN:
        msg = "PaaS token 未配置"
        return _response_envelope(payload, {"can_create": False, "reason": msg, "checks": []}, 500, msg, -1)

    client = PaasClient(Config.DCE_API_BASE, Config.DCE_TOKEN)
    # 第一步：查询集群资源汇总，用于计算 GPU 总量、CPU/内存 allocatable 与 allocated。
    cluster_path = f"/clusters/{Config.DCE_CLUSTER}"
    cluster_status, cluster_result = client.request_with_status("GET", cluster_path)
    if cluster_status != 200 or not isinstance(cluster_result, dict):
        msg = "无法获取资源汇总"
        return _response_envelope(
            payload,
            {
                "can_create": False,
                "reason": msg,
                "checks": [],
                "response": cluster_result,
            },
            502 if cluster_status != 504 else 504,
            msg,
            -1,
        )

    # 第二步：查询当前命名空间下已有 Deployment。旧脚本约定一个 Deployment 近似占一张卡。
    deployment_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/deployments"
    deploy_status, deploy_result = client.request_with_status("GET", deployment_path)
    if deploy_status != 200:
        msg = "获取部署列表失败"
        return _response_envelope(
            payload,
            {
                "can_create": False,
                "reason": msg,
                "checks": [],
                "response": deploy_result,
            },
            502 if deploy_status != 504 else 504,
            msg,
            -1,
        )

    deployments = _deployment_items(deploy_result)
    allocatable = (cluster_result.get("status", {}) or {}).get("resourceSummary", {}).get("allocatable", {}) or {}
    allocated = (cluster_result.get("status", {}) or {}).get("resourceSummary", {}).get("allocated", {}) or {}

    resource_name = device_request["resource_name"]
    gpu_total = _parse_int_quantity(allocatable.get(resource_name))

    # 创建准入优先复用资源中心节点明细，与首页"物理卡 3/4"保持同一统计口径。
    # 取不到时再回退到节点 raw allocatable + 活跃 Pod requests/limits 计算。
    node_gpu_usage, node_gpu_error = _node_resource_usage_from_resource_nodes(resource_name)
    gpu_used_source = "resources_nodes"
    if not node_gpu_usage:
        node_gpu_usage, node_gpu_error = _node_resource_usage_from_paas(client, resource_name)
        gpu_used_source = "node_raw_allocatable_and_active_pods"
    if node_gpu_usage:
        gpu_total = node_gpu_usage["total"]
        gpu_used = node_gpu_usage["used"]
        gpu_available = node_gpu_usage["available"]
    elif resource_name in allocated:
        gpu_used = _parse_int_quantity(allocated.get(resource_name))
        gpu_used_source = "resourceSummary.allocated"
        gpu_available = max(gpu_total - gpu_used, 0)
    else:
        gpu_used = len(deployments)
        gpu_used_source = "deployment_count_fallback"
        gpu_available = max(gpu_total - gpu_used, 0)
    requested = device_request["requested"]

    checks = []
    # 检查项 1：GPU 可用余量。页面展示"可用 N 张"，比"资源设备可用"更贴近原脚本逻辑。
    gpu_detail = {
        "resource_name": resource_name,
        "device_key": device_request["device_key"],
        "requested": requested,
        "available": gpu_available,
        "total": gpu_total,
        "used": gpu_used,
        "used_source": gpu_used_source,
        "vendor": device_request["vendor"],
    }
    if node_gpu_usage:
        gpu_detail["total_available"] = node_gpu_usage["total_available"]
        gpu_detail["nodes"] = node_gpu_usage["nodes"]
    elif node_gpu_error:
        gpu_detail["node_usage_error"] = node_gpu_error
    if gpu_available >= requested:
        checks.append(_passed_check("gpu_available", "GPU 可用余量", f"可用 {gpu_available} / {gpu_total} 张", gpu_detail))
    else:
        checks.append(
            _failed_check(
                "gpu_available",
                "GPU 可用余量",
                f"可用 {gpu_available} / {gpu_total} 张",
                f"当前可用 {gpu_available} 张，申请 {requested} 张",
                gpu_detail,
            )
        )

    cpu_available_m = _parse_cpu_m(allocatable.get("cpu")) - _parse_cpu_m(allocated.get("cpu"))
    mem_available_bytes = _parse_memory_bytes(allocatable.get("memory")) - _parse_memory_bytes(allocated.get("memory"))
    # 检查项 2：CPU/内存余量。沿用旧脚本最低门槛：CPU 2000m、内存 4GiB。
    cpu_mem_detail = {
        "cpu_available_m": cpu_available_m,
        "cpu_required_m": MIN_CPU_M,
        "mem_available_bytes": mem_available_bytes,
        "mem_required_bytes": MIN_MEM_BYTES,
    }
    cpu_mem_reasons = []
    if cpu_available_m < MIN_CPU_M:
        cpu_mem_reasons.append(f"CPU 可用 {cpu_available_m}m，需至少 {MIN_CPU_M}m")
    if mem_available_bytes < MIN_MEM_BYTES:
        cpu_mem_reasons.append(f"内存可用 {mem_available_bytes}B，需至少 {MIN_MEM_BYTES}B")
    if cpu_mem_reasons:
        checks.append(
            _failed_check(
                "cpu_memory",
                "CPU / 内存余量",
                "未通过",
                "；".join(cpu_mem_reasons),
                cpu_mem_detail,
            )
        )
    else:
        checks.append(_passed_check("cpu_memory", "CPU / 内存余量", "通过", cpu_mem_detail))

    # 检查项 3：NodePort 自动避让。这里只确认"存在可选端口"，不提前占用端口。
    # 读取封闭端口（NodePort 和 SubPort 检查共用）
    try:
        blocked_ports = set(resolve_blocked_ports().get("blocked_ports", []))
        blocked_error = None
    except Exception as exc:
        blocked_ports = set()
        blocked_error = str(exc)

    service_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/services"
    service_status, service_result = client.request_with_status("GET", service_path)
    if service_status == 200:
        service_ports = _existing_node_ports(service_result)

        unavailable_ports = {
            port for port in service_ports.union(blocked_ports)
            if NODEPORT_START <= port <= NODEPORT_END
        }
        has_candidate = len(unavailable_ports) < (NODEPORT_END - NODEPORT_START + 1)
        nodeport_detail = {
            "range_start": NODEPORT_START,
            "range_end": NODEPORT_END,
            "service_node_ports": sorted(service_ports),
            "blocked_ports": sorted(blocked_ports),
            "unavailable_count": len(unavailable_ports),
        }
        if blocked_error:
            checks.append(
                _failed_check(
                    "nodeport",
                    "NodePort 自动避让",
                    "未通过",
                    f"读取封闭端口失败：{blocked_error}",
                    nodeport_detail,
                )
            )
        elif has_candidate:
            checks.append(_passed_check("nodeport", "NodePort 自动避让", "通过", nodeport_detail))
        else:
            checks.append(
                _failed_check(
                    "nodeport",
                    "NodePort 自动避让",
                    "未通过",
                    "NodePort 可选范围已无可用端口",
                    nodeport_detail,
                )
            )
    else:
        service_ports = set()
        checks.append(
            _failed_check(
                "nodeport",
                "NodePort 自动避让",
                "未通过",
                "获取 Service 列表失败，无法确认 NodePort 可避让",
                {"response": service_result},
            )
        )

    # 检查项 4：SubPort 端口指定。用户可选指定 tcp_8019 端口，不指定则跳过此检查。
    check_subport, subport_parse_error = parse_optional_subport(payload.get("content", {}) or {})
    if subport_parse_error:
        checks.append(
            _failed_check(
                "subport",
                "SubPort 端口指定",
                "未通过",
                subport_parse_error,
                {"subport": (payload.get("content", {}) or {}).get("subport")},
            )
        )
    elif check_subport is not None:
        subport_conflicts = []
        if check_subport in blocked_ports:
            subport_conflicts.append("已被封闭")
        if check_subport in service_ports:
            subport_conflicts.append("已被现有 Service 占用")
        subport_detail = {
            "subport": check_subport,
            "blocked_ports": sorted(blocked_ports),
            "service_node_ports": sorted(service_ports),
        }
        if subport_conflicts:
            checks.append(
                _failed_check(
                    "subport",
                    "SubPort 端口指定",
                    "未通过",
                    f"端口 {check_subport} " + "；".join(subport_conflicts),
                    subport_detail,
                )
            )
        else:
            checks.append(_passed_check("subport", "SubPort 端口指定", f"端口 {check_subport} 可用", subport_detail))

    deploy_name = get_deploy_name(payload)
    # 检查项 5：同名部署校验。没有传 name 时允许通过，创建接口最终生成名称后还要再校验。
    if deploy_name and _deployment_exists(deployments, deploy_name):
        checks.append(
            _failed_check(
                "deploy_lock",
                "部署锁与并发校验",
                "未通过",
                f"部署 {deploy_name} 已存在",
                {"deployment_name": deploy_name},
            )
        )
    else:
        checks.append(_passed_check("deploy_lock", "部署锁与并发校验", "通过", {"deployment_name": deploy_name or None}))

    failed_checks = [check for check in checks if check["status"] == "failed"]
    # 只要任一检查项失败，就不允许创建；reason 取第一个失败项，便于前端顶部展示。
    can_create = not failed_checks
    reason = "资源预检通过" if can_create else failed_checks[0].get("message", "资源预检未通过")
    http_status = 200 if can_create else 400

    content = {
        "can_create": can_create,
        "reason": reason,
        "checks": checks,
        "cpu_available_m": cpu_available_m,
        "mem_available_bytes": mem_available_bytes,
        "gpu_details": {
            resource_name: {
                "requested": requested,
                "available": gpu_available,
                "total": gpu_total,
                "used": gpu_used,
                "used_source": gpu_used_source,
            }
        },
        "total_deployments": gpu_used,
        "devices": (payload.get("content", {}) or {}).get("devices", {}),
    }
    return _response_envelope(payload, content, http_status, reason, 0 if can_create else -1)


def create_default(payload: dict) -> tuple[dict, int]:
    valid, message = validate_deploy_envelope(payload, "create")
    if not valid:
        return _response_envelope(payload, {"error": message}, 400, message, -1), 400

    valid, message = validate_create_payload(payload)
    if not valid:
        return _response_envelope(payload, {"error": message}, 400, message, -1), 400

    device_request, error = _extract_device_request(payload)
    if error:
        return _response_envelope(payload, {"error": error}, 400, error, -1), 400
    if device_request["vendor"] != "NVIDIA":
        msg = "当前集群暂不支持 Huawei/Ascend310P"
        return _response_envelope(payload, {"error": msg}, 400, msg, -1), 400
    if not Config.DCE_API_BASE:
        msg = "PaaS 地址未配置"
        return _response_envelope(payload, {"error": "DCE_API_BASE is not configured"}, 500, msg, -1), 500
    if not Config.DCE_TOKEN:
        msg = "PaaS token 未配置"
        return _response_envelope(payload, {"error": "DCE_TOKEN is not configured"}, 500, msg, -1), 500

    content = payload.get("content", {}) or {}
    specified_subport, subport_error = parse_optional_subport(content)
    if subport_error:
        return _response_envelope(payload, {"error": subport_error}, 400, subport_error, -1), 400

    deploy_type = str(content.get("deployType") or device_request["deploy_type"])
    creator = _current_creator(payload)
    client_ip = _get_client_ip()
    workshop_mode = _is_workshop_request(client_ip)
    client = PaasClient(Config.DCE_API_BASE, Config.DCE_TOKEN)

    try:
        with repository.deploy_create_lock():
            # 创建链路必须在锁内重新预检，避免并发请求同时穿透资源和端口判断。
            precheck_ok, precheck_result, precheck_http_status = _precheck_passed(
                payload,
                ignore_nodeport=workshop_mode,
            )
            if not precheck_ok:
                return precheck_result, precheck_http_status

            name = f"nvidia-cuda-{uuid.uuid4().hex[:6]}"
            instance_name = str(content.get("instance_name") or "").strip() or name
            if specified_subport is not None:
                subport = specified_subport
            elif workshop_mode:
                subport = WORKSHOP_PORT_8019
            else:
                subport, port_error, port_status = _select_subport(client)
                if port_error is not None or subport is None:
                    msg = "可用端口选择失败"
                    return _response_envelope(payload, port_error or {}, port_status, msg, -1), port_status

            deployment = _build_deployment(
                name=name,
                instance_name=instance_name,
                client_ip=client_ip,
                deploy_type=deploy_type,
                device_request=device_request,
                subport=subport,
                workshop_mode=workshop_mode,
            )
            deploy_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/deployments/json"
            deploy_status, deploy_result = client.request_with_status(
                "POST",
                deploy_path,
                json_body=_paas_json_payload("deployments", deployment),
            )
            if not 200 <= deploy_status < 300:
                msg = "Deployment 创建失败"
                return _response_envelope(
                    payload,
                    {"error": msg, "response": deploy_result},
                    deploy_status,
                    msg,
                    -1,
                ), deploy_status

            node_ports = []
            if workshop_mode:
                node_ports = [
                    {"name": "tcp-8018", "port": WORKSHOP_PORT_8018},
                    {"name": "tcp-8019", "port": WORKSHOP_PORT_8019},
                ]
                service_created = False
            else:
                service = _build_service(
                    name=name,
                    instance_name=instance_name,
                    client_ip=client_ip,
                    deploy_type=deploy_type,
                )
                service_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/services"
                service_status, service_result = client.request_with_status(
                    "POST",
                    service_path,
                    json_body=_paas_json_payload("", service),
                )
                if not 200 <= service_status < 300:
                    _rollback_created_resources(client, name, service_created=False)
                    msg = "Service 创建失败"
                    return _response_envelope(
                        payload,
                        {
                            "error": msg,
                            "response": service_result,
                            "rollback": "deployment delete requested",
                        },
                        service_status,
                        msg,
                        -1,
                    ), service_status

                node_ports = _service_nodeports_with_retry(client, name)
                node_ports.append({"name": "tcp-8019", "port": subport})
                service_created = True

            log_source = "paas"
            record = build_deploy_record(
                name,
                {**payload, "content": {**content, "creator": creator}},
                gpu_vendor=device_request["vendor"],
                node_ports=node_ports,
                log_path=None,
                status="running",
            )
            try:
                repository.save_deploy_instance(record)
            except Exception as exc:
                _rollback_created_resources(client, name, service_created=service_created)
                msg = "实例记录写入失败"
                return _response_envelope(
                    payload,
                    {
                        "error": str(exc),
                        "rollback": "created paas resources delete requested",
                    },
                    500,
                    msg,
                    -1,
                ), 500

            response_content = {
                "deployment_name": name,
                "node_ports": node_ports,
                "devices": content.get("devices", {}),
                "gpu_type": device_request["device_key"],
                "deployType": deploy_type,
                "log_path": None,
                "log_source": log_source,
                "workshop_mode": workshop_mode,
                "client_ip": client_ip,
            }
            return _response_envelope(payload, response_content, 200, "OK", 0), 200
    except repository.DeployCreateLockError as exc:
        msg = str(exc)
        return _response_envelope(payload, {"error": msg}, 409, msg, -1), 409
    except Exception as exc:
        msg = "创建部署失败"
        return _response_envelope(payload, {"error": str(exc)}, 500, msg, -1), 500


def retrieve(payload: dict) -> tuple[dict, int]:
    valid, message = validate_deploy_envelope(payload, "retrieve")
    if not valid:
        return _response_envelope(payload, {"error": message}, 400, message, -1), 400

    name = get_deploy_name(payload)
    if not name:
        msg = "缺少必填字段：content.name"
        return _response_envelope(payload, {"error": msg}, 400, msg, -1), 400
    if not Config.DCE_API_BASE:
        msg = "PaaS 地址未配置"
        return _response_envelope(payload, {"error": "DCE_API_BASE is not configured"}, 500, msg, -1), 500
    if not Config.DCE_TOKEN:
        msg = "PaaS token 未配置"
        return _response_envelope(payload, {"error": "DCE_TOKEN is not configured"}, 500, msg, -1), 500

    try:
        client = PaasClient(Config.DCE_API_BASE, Config.DCE_TOKEN)
        deployment_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/deployments/{name}"
        deployment_status, deployment_result = client.request_with_status("GET", deployment_path)
        if deployment_status == 404:
            msg = f"部署 {name} 不存在"
            return _response_envelope(
                payload,
                {"deployment_name": name, "response": deployment_result},
                404,
                msg,
                -1,
            ), 404
        if not 200 <= deployment_status < 300:
            msg = "部署查询超时" if deployment_status == 504 else "部署查询失败"
            return _response_envelope(
                payload,
                {"deployment_name": name, "response": deployment_result},
                deployment_status,
                msg,
                -1,
            ), deployment_status

        service_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/services/{name}"
        service_status, service_result = client.request_with_status("GET", service_path)
        node_ports = service_node_ports(service_result) if service_status == 200 and isinstance(service_result, dict) else []

        # 旧脚本使用 app=<deployment_name> 关联 Pod；创建接口也写入同名 app label。
        pod_path = deployment_pod_path(Config.DCE_CLUSTER, Config.DCE_NAMESPACE, name)
        pod_status, pod_result = client.request_with_status("GET", pod_path)
        pods = []
        deployment = summarize_deployment(deployment_result)
        record = repository.get_deploy_instance(name) or {}
        summary = summarize_pods(pods)
        first_pod = {}
        gpu_resources = gpu_resource_limits(deployment_result)
        gpu_text = " / ".join(f"{key} x{value}" for key, value in gpu_resources.items()) or "GPU x0"
        open_ports = [item.get("port") for item in node_ports if item.get("port") is not None]
        if pod_status == 200:
            pods = [summarize_pod(pod) for pod in pod_items(pod_result) if isinstance(pod, dict)]
            summary = summarize_pods(pods)
            first_pod = pods[0] if pods else {}

        # 查询详情只返回前端展示字段，不透传 PaaS 原始对象，也不写数据库。
        content = {
            "deployment_name": name,
            "instance_name": record.get("instance_name") or deployment.get("instance_name") or name,
            "status": deployment.get("state") or first_pod.get("phase"),
            "creator": record.get("creator") or deployment.get("creator"),
            "created_at": deployment.get("created_at") or record.get("created_at"),
            "deploy_area": first_pod.get("node_name"),
            "replica_count": f"{summary['ready_pods']}/{deployment.get('replicas', 0)} 个",
            "service_endpoint": deployment.get("creator_ip"),
            "open_ports": open_ports,
            "resource_mode": "物理 GPU",
            "bound_resource": f"{first_pod.get('node_name') or '-'} / {gpu_text}",
        }

        return _response_envelope(payload, content, 200, "OK", 0), 200
    except Exception as exc:
        msg = "部署查询异常"
        return _response_envelope(payload, {"deployment_name": name, "error": str(exc)}, 500, msg, -1), 500


def _deploy_name_or_error(payload: dict) -> tuple[str, dict | None]:
    name = get_deploy_name(payload)
    if name:
        return name, None
    msg = "缺少必填字段：content.name"
    return "", _response_envelope(payload, {"error": msg}, 400, msg, -1)


def _deploy_client_or_error(payload: dict) -> tuple[PaasClient | None, dict | None]:
    if not Config.DCE_API_BASE:
        msg = "PaaS 地址未配置"
        return None, _response_envelope(payload, {"error": "DCE_API_BASE is not configured"}, 500, msg, -1)
    if not Config.DCE_TOKEN:
        msg = "PaaS token 未配置"
        return None, _response_envelope(payload, {"error": "DCE_TOKEN is not configured"}, 500, msg, -1)
    return PaasClient(Config.DCE_API_BASE, Config.DCE_TOKEN), None


def _k8s_client_or_error(payload: dict) -> tuple[K8sClient | None, dict | None]:
    client = K8sClient.from_config(Config)
    if not client.api_base:
        msg = "Kubernetes API 地址未配置"
        return None, _response_envelope(payload, {"error": "K8S_API_BASE is not configured"}, 500, msg, -1)
    if not client.token:
        msg = "Kubernetes token 未配置"
        return None, _response_envelope(payload, {"error": "K8S_TOKEN is not configured"}, 500, msg, -1)
    return client, None


def _delete_paas_resource(client: PaasClient, path: str) -> tuple[dict, bool]:
    status_code, result = client.request_with_status("DELETE", path)
    ok = 200 <= status_code < 300 or status_code == 404
    return {
        "http_status_code": status_code,
        "is_success": ok,
        "not_found_ignored": status_code == 404,
        "response": result,
    }, ok


def _scale_deployment(client: PaasClient, name: str, replicas: int) -> tuple[int, dict]:
    # PaaS/DCE 优先使用 Kubernetes scale 子资源；若环境不支持，再退回 patch deployment spec。
    scale_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/deployments/{name}/scale"
    scale_body = {"spec": {"replicas": replicas}}
    status_code, result = client.request_with_status("PATCH", scale_path, json_body=scale_body)
    if 200 <= status_code < 300:
        return status_code, result

    patch_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/deployments/{name}"
    patch_body = {"spec": {"replicas": replicas}}
    fallback_status, fallback_result = client.request_with_status("PATCH", patch_path, json_body=patch_body)
    if 200 <= fallback_status < 300:
        return fallback_status, fallback_result

    return fallback_status, {
        "scale": {"http_status_code": status_code, "response": result},
        "patch": {"http_status_code": fallback_status, "response": fallback_result},
    }


def _pod_log_lines(result) -> list[str]:
    if isinstance(result, list):
        return [str(item) for item in result]
    if not isinstance(result, dict):
        text = str(result or "")
        return text.splitlines() if text else []

    for key in ("lines", "logs", "items"):
        value = result.get(key)
        if isinstance(value, list):
            return [str(item) for item in value]

    for key in ("log", "content", "raw"):
        value = result.get(key)
        if isinstance(value, str):
            return value.splitlines()
    return []


def _pod_event_items(result) -> list[dict]:
    if not isinstance(result, dict):
        return []
    events = []
    for item in result.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        events.append(
            {
                "type": item.get("type"),
                "reason": item.get("reason"),
                "message": item.get("message"),
                "source": (item.get("source") or {}).get("component") or item.get("reportingComponent"),
                "first_timestamp": item.get("firstTimestamp") or item.get("eventTime"),
                "last_timestamp": item.get("lastTimestamp") or item.get("eventTime"),
                "count": item.get("count"),
            }
        )
    return events


def _describe_time(value) -> str:
    return str(value or "<none>")


def _describe_list(values) -> str:
    if not values:
        return "      <none>"
    return "\n".join(f"      {value}" for value in values)


def _resource_lines(resources: dict, key: str) -> list[str]:
    values = (resources.get(key) or {}) if isinstance(resources, dict) else {}
    if not values:
        return [f"    {key.title()}:           <none>"]
    lines = [f"    {key.title()}:"]
    for name, value in values.items():
        lines.append(f"      {name}:  {value}")
    return lines


def _container_status_by_name(statuses: list[dict]) -> dict:
    return {
        item.get("name"): item
        for item in statuses or []
        if isinstance(item, dict) and item.get("name")
    }


def _container_state_lines(status: dict) -> list[str]:
    state = (status or {}).get("state") or {}
    if "running" in state:
        running = state["running"] or {}
        return [
            "    State:          Running",
            f"      Started:      {_describe_time(running.get('startedAt'))}",
        ]
    if "terminated" in state:
        terminated = state["terminated"] or {}
        return [
            "    State:          Terminated",
            f"      Reason:       {terminated.get('reason') or '<none>'}",
            f"      Exit Code:    {terminated.get('exitCode') if terminated.get('exitCode') is not None else '<none>'}",
            f"      Started:      {_describe_time(terminated.get('startedAt'))}",
            f"      Finished:     {_describe_time(terminated.get('finishedAt'))}",
        ]
    if "waiting" in state:
        waiting = state["waiting"] or {}
        return [
            "    State:          Waiting",
            f"      Reason:       {waiting.get('reason') or '<none>'}",
            f"      Message:      {waiting.get('message') or '<none>'}",
        ]
    return ["    State:          <none>"]


def _container_describe_lines(container: dict, status: dict | None = None) -> list[str]:
    status = status or {}
    lines = [
        f"  {container.get('name')}:",
        f"    Container ID:  {status.get('containerID') or '<none>'}",
        f"    Image:         {container.get('image') or '<none>'}",
        f"    Image ID:      {status.get('imageID') or '<none>'}",
    ]
    ports = container.get("ports") or []
    if ports:
        port_text = ", ".join(f"{item.get('containerPort')}/{item.get('protocol', 'TCP')}" for item in ports)
        host_port_text = ", ".join(f"{item.get('hostPort', 0)}/{item.get('protocol', 'TCP')}" for item in ports)
    else:
        port_text = "<none>"
        host_port_text = "<none>"
    lines.extend([
        f"    Port:          {port_text}",
        f"    Host Port:     {host_port_text}",
        "    Command:",
        _describe_list(container.get("command")),
        "    Args:",
        _describe_list(container.get("args")),
    ])
    lines.extend(_container_state_lines(status))
    lines.extend([
        f"    Ready:          {status.get('ready') if status.get('ready') is not None else '<none>'}",
        f"    Restart Count:  {status.get('restartCount', 0)}",
    ])
    lines.extend(_resource_lines(container.get("resources") or {}, "limits"))
    lines.extend(_resource_lines(container.get("resources") or {}, "requests"))
    env = container.get("env") or []
    lines.append("    Environment:    <none>" if not env else "    Environment:")
    for item in env:
        lines.append(f"      {item.get('name')}:  {item.get('value') or '<set>'}")
    mounts = container.get("volumeMounts") or []
    lines.append("    Mounts:")
    if mounts:
        for item in mounts:
            mode = "ro" if item.get("readOnly") else "rw"
            lines.append(f"      {item.get('mountPath')} from {item.get('name')} ({mode})")
    else:
        lines.append("      <none>")
    return lines


def _volume_describe_lines(volume: dict) -> list[str]:
    name = volume.get("name")
    lines = [f"  {name}:"]
    if "emptyDir" in volume:
        empty_dir = volume.get("emptyDir") or {}
        lines.extend([
            "    Type:       EmptyDir (a temporary directory that shares a pod's lifetime)",
            f"    Medium:     {empty_dir.get('medium') or ''}",
            f"    SizeLimit:  {empty_dir.get('sizeLimit') or '<unset>'}",
        ])
    elif "hostPath" in volume:
        host_path = volume.get("hostPath") or {}
        lines.extend([
            "    Type:          HostPath (bare host directory volume)",
            f"    Path:          {host_path.get('path') or '<none>'}",
            f"    HostPathType:  {host_path.get('type') or ''}",
        ])
    elif "projected" in volume:
        lines.append("    Type:                    Projected")
    else:
        lines.append("    Type:       <unknown>")
    return lines


def _event_describe_lines(events: list[dict], event_error: dict | None = None) -> list[str]:
    lines = [
        "Events:",
        "  Type     Reason            Age   From               Message",
        "  ----     ------            ----  ----               -------",
    ]
    if event_error:
        message = ((event_error.get("response") or {}).get("message") or str(event_error))
        lines.append(f"  Warning  Forbidden         -     apiserver          {message}")
        return lines
    if not events:
        lines.append("  <none>")
        return lines
    for event in events:
        lines.append(
            f"  {event.get('type') or '<none>':<8} "
            f"{event.get('reason') or '<none>':<17} "
            f"{event.get('last_timestamp') or '-':<5} "
            f"{event.get('source') or '<none>':<18} "
            f"{event.get('message') or ''}"
        )
    return lines


def _pod_describe_text(pod: dict, events: list[dict], event_error: dict | None = None) -> str:
    metadata = pod.get("metadata") or {}
    spec = pod.get("spec") or {}
    status = pod.get("status") or {}
    labels = metadata.get("labels") or {}
    annotations = metadata.get("annotations") or {}
    owner_refs = metadata.get("ownerReferences") or []
    init_statuses = _container_status_by_name(status.get("initContainerStatuses") or [])
    container_statuses = _container_status_by_name(status.get("containerStatuses") or [])

    lines = [
        f"Name:             {metadata.get('name') or '<none>'}",
        f"Namespace:        {metadata.get('namespace') or '<none>'}",
        f"Priority:         {spec.get('priority') if spec.get('priority') is not None else 0}",
        f"Service Account:  {spec.get('serviceAccountName') or '<none>'}",
        f"Node:             {spec.get('nodeName') or '<none>'}/{status.get('hostIP') or '<none>'}",
        f"Start Time:       {_describe_time(status.get('startTime'))}",
        "Labels:",
    ]
    if labels:
        first = True
        for key, value in labels.items():
            prefix = "  " if first else "                  "
            lines.append(f"{prefix}{key}={value}")
            first = False
    else:
        lines.append("  <none>")
    lines.append("Annotations:")
    if annotations:
        first = True
        for key, value in annotations.items():
            prefix = "  " if first else "                  "
            lines.append(f"{prefix}{key}: {value}")
            first = False
    else:
        lines.append("  <none>")
    lines.extend([
        f"Status:           {status.get('phase') or '<none>'}",
        f"IP:               {status.get('podIP') or '<none>'}",
        "IPs:",
        f"  IP:           {status.get('podIP') or '<none>'}",
    ])
    if owner_refs:
        owner = owner_refs[0]
        lines.append(f"Controlled By:  {owner.get('kind')}/{owner.get('name')}")
    init_containers = spec.get("initContainers") or []
    if init_containers:
        lines.append("Init Containers:")
        for container in init_containers:
            lines.extend(_container_describe_lines(container, init_statuses.get(container.get("name"))))
    containers = spec.get("containers") or []
    if containers:
        lines.append("Containers:")
        for container in containers:
            lines.extend(_container_describe_lines(container, container_statuses.get(container.get("name"))))
    lines.append("Conditions:")
    lines.append("  Type              Status")
    for condition in status.get("conditions") or []:
        lines.append(f"  {condition.get('type'):<17} {condition.get('status')}")
    lines.append("Volumes:")
    for volume in spec.get("volumes") or []:
        lines.extend(_volume_describe_lines(volume))
    lines.extend([
        f"QoS Class:                   {status.get('qosClass') or '<none>'}",
        "Node-Selectors:              <none>" if not spec.get("nodeSelector") else f"Node-Selectors:              {spec.get('nodeSelector')}",
        "Tolerations:",
    ])
    tolerations = spec.get("tolerations") or []
    if tolerations:
        for item in tolerations:
            effect = f":{item.get('effect')}" if item.get("effect") else ""
            seconds = f" for {item.get('tolerationSeconds')}s" if item.get("tolerationSeconds") is not None else ""
            lines.append(f"  {item.get('key')}:{item.get('operator') or 'Equal'}{effect}{seconds}")
    else:
        lines.append("  <none>")
    lines.extend(_event_describe_lines(events, event_error))
    return "\n".join(lines)


def _pod_delete_targets(pods: list[dict]) -> list[dict]:
    running_pods = [pod for pod in pods if pod.get("phase") == "Running"]
    return running_pods or pods


def release(payload: dict) -> dict:
    valid, message = validate_deploy_envelope(payload, "release")
    if not valid:
        return _response_envelope(payload, {"error": message}, 400, message, -1)

    name, error_response = _deploy_name_or_error(payload)
    if error_response:
        return error_response
    client, error_response = _deploy_client_or_error(payload)
    if error_response:
        return error_response

    try:
        service_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/services/{name}"
        deployment_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/deployments/{name}"
        service_delete, service_ok = _delete_paas_resource(client, service_path)
        deployment_delete, deployment_ok = _delete_paas_resource(client, deployment_path)
        if not service_ok or not deployment_ok:
            msg = "释放部署失败"
            return _response_envelope(
                payload,
                {
                    "deployment_name": name,
                    "service_delete": service_delete,
                    "deployment_delete": deployment_delete,
                },
                502,
                msg,
                -1,
            )

        update_result = repository.delete_deploy_instance(name)
        content = {
            "deployment_name": name,
            "status": "released",
            "deployment_delete": deployment_delete,
            "service_delete": service_delete,
            "db_update": update_result,
        }
        return _response_envelope(payload, content, 200, "OK", 0)
    except Exception as exc:
        msg = "释放部署异常"
        return _response_envelope(payload, {"deployment_name": name, "error": str(exc)}, 500, msg, -1)


def reset(payload: dict) -> dict:
    valid, message = validate_deploy_envelope(payload, "reset")
    if not valid:
        return _response_envelope(payload, {"error": message}, 400, message, -1)

    name, error_response = _deploy_name_or_error(payload)
    if error_response:
        return error_response
    client, error_response = _deploy_client_or_error(payload)
    if error_response:
        return error_response

    # GPU 单副本部署不能直接 rollout restart，否则会先创建新 Pod 导致 GPU 不足；这里删除旧 Pod，由 Deployment 自动拉起新 Pod。
    pod_path = deployment_pod_path(Config.DCE_CLUSTER, Config.DCE_NAMESPACE, name)
    pod_status, pod_result = client.request_with_status("GET", pod_path)
    if pod_status != 200:
        msg = "查询部署 Pod 失败"
        return _response_envelope(
            payload,
            {"deployment_name": name, "response": pod_result},
            pod_status,
            msg,
            -1,
        )

    pods = [
        summarize_pod(pod)
        for pod in pod_items(pod_result)
        if isinstance(pod, dict)
    ]
    targets = _pod_delete_targets(pods)
    if not targets:
        msg = "部署暂无可重启的 Pod"
        return _response_envelope(payload, {"deployment_name": name, "pods": []}, 404, msg, -1)

    pod_deletes = []
    all_deleted = True
    for pod in targets:
        pod_name = pod.get("pod_name")
        delete_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/pods/{pod_name}"
        delete_result, delete_ok = _delete_paas_resource(client, delete_path)
        pod_deletes.append({"pod_name": pod_name, **delete_result})
        all_deleted = all_deleted and delete_ok

    if not all_deleted:
        msg = "重启部署失败"
        return _response_envelope(
            payload,
            {"deployment_name": name, "pod_deletes": pod_deletes},
            502,
            msg,
            -1,
        )

    update_result = repository.update_deploy_status(name, "running")
    return _response_envelope(
        payload,
        {"deployment_name": name, "status": "running", "pod_deletes": pod_deletes, "db_update": update_result},
        200,
        "OK",
        0,
    )


def stop(payload: dict) -> dict:
    valid, message = validate_deploy_envelope(payload, "stop")
    if not valid:
        return _response_envelope(payload, {"error": message}, 400, message, -1)

    name, error_response = _deploy_name_or_error(payload)
    if error_response:
        return error_response
    client, error_response = _k8s_client_or_error(payload)
    if error_response:
        return error_response

    # 停止部署直接走 Kubernetes API 缩容到 0，避免 PaaS scale/patch 包装格式不兼容。
    status_code, result = client.patch_deployment_replicas(Config.DCE_NAMESPACE, name, 0)
    if not 200 <= status_code < 300:
        msg = "停止部署失败"
        return _response_envelope(
            payload,
            {"deployment_name": name, "response": result},
            status_code,
            msg,
            -1,
        )

    update_result = repository.update_deploy_status(name, "stopped")
    return _response_envelope(
        payload,
        {"deployment_name": name, "status": "stopped", "response": result, "db_update": update_result},
        200,
        "OK",
        0,
    )


def logs(payload: dict) -> dict:
    valid, message = validate_deploy_envelope(payload, "logs")
    if not valid:
        return _response_envelope(payload, {"error": message}, 400, message, -1)

    name, error_response = _deploy_name_or_error(payload)
    if error_response:
        return error_response
    client, error_response = _k8s_client_or_error(payload)
    if error_response:
        return error_response

    # 前端只传 deployment_name；后端先通过 Kubernetes app label 找到真实 Pod 名称，
    # 再读取 Pod 对象并拼出接近 `kubectl describe pod` 的完整描述文本。
    pod_status, pod_result = client.list_pods_by_app(Config.DCE_NAMESPACE, name)
    if pod_status != 200:
        msg = "查询部署 Pod 失败"
        return _response_envelope(
            payload,
            {"deployment_name": name, "response": pod_result},
            pod_status,
            msg,
            -1,
        )

    pods = [
        summarize_pod(pod)
        for pod in pod_items(pod_result)
        if isinstance(pod, dict)
    ]
    pod = next((item for item in pods if item.get("phase") == "Running"), None) or (pods[0] if pods else {})
    pod_name = pod.get("pod_name")
    if not pod_name:
        msg = "部署暂无可描述的 Pod"
        return _response_envelope(payload, {"deployment_name": name, "describe": ""}, 404, msg, -1)

    pod_read_status, pod_read_result = client.read_pod(Config.DCE_NAMESPACE, pod_name)
    if not 200 <= pod_read_status < 300 or not isinstance(pod_read_result, dict):
        msg = "部署 Pod 描述查询失败"
        return _response_envelope(
            payload,
            {"deployment_name": name, "pod_name": pod_name, "response": pod_read_result},
            pod_read_status,
            msg,
            -1,
        )

    event_status, event_result = client.list_events(Config.DCE_NAMESPACE, pod_name)
    events = _pod_event_items(event_result) if 200 <= event_status < 300 else []
    event_error = None if 200 <= event_status < 300 else {"status": event_status, "response": event_result}
    describe = _pod_describe_text(pod_read_result, events, event_error)
    return _response_envelope(
        payload,
        {
            "deployment_name": name,
            "pod_name": pod_name,
            "describe": describe,
        },
        200,
        "OK",
        0,
    )


def _format_list_created_at(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.isdigit():
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(text)))
    return text.replace("T", " ").replace("Z", "")[:19]


def _deployment_display_status(deployment: dict, record: dict | None = None, pods: list[dict] | None = None) -> str:
    local_status = str((record or {}).get("status") or "").lower()
    pods = pods or []
    replicas = _parse_int_quantity(deployment.get("replicas"))
    available = _parse_int_quantity(deployment.get("available_replicas"))
    ready = _parse_int_quantity(deployment.get("ready_replicas"))
    state = str(deployment.get("state") or "").lower()
    has_available_condition = any(
        item.get("type") == "Available" and item.get("status") == "True"
        for item in deployment.get("conditions", []) or []
    )

    if local_status == "stopped" or (replicas == 0 and available == 0 and ready == 0):
        return "已停止"
    if state == "running" or has_available_condition or (replicas > 0 and available >= replicas and ready >= replicas):
        return "已部署"
    if any(pod.get("phase") == "Pending" for pod in pods) or (replicas > 0 and ready < replicas and available < replicas):
        return "等待"
    return "异常"


def _deployment_list_total(result: dict) -> int:
    if not isinstance(result, dict):
        return 0
    candidates = [
        result.get("total"),
        result.get("totalCount"),
        result.get("count"),
        (result.get("metadata") or {}).get("total"),
        (result.get("pagination") or {}).get("total"),
    ]
    for value in candidates:
        try:
            total = int(value)
            if total > 0:
                return total
        except (TypeError, ValueError):
            continue
    return 0


def _deployment_list_path(page: int | None = None, page_size: int | None = None) -> str:
    path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/deployments"
    if page is None or page_size is None:
        return path
    return f"{path}?page={page}&pageSize={page_size}"


def _list_namespace_deployments(client: PaasClient) -> tuple[int, dict]:
    page_size = max(DEPLOYMENT_LIST_PAGE_SIZE, 10)
    status, result = client.request_with_status("GET", _deployment_list_path(1, page_size))
    if not 200 <= status < 300:
        return client.request_with_status("GET", _deployment_list_path())

    items = _deployment_items(result)
    total = _deployment_list_total(result)
    if not total or len(items) >= total:
        merged = dict(result) if isinstance(result, dict) else {}
        merged["items"] = items
        return status, merged

    all_items = list(items)
    page = 2
    while len(all_items) < total and page <= 50:
        page_status, page_result = client.request_with_status("GET", _deployment_list_path(page, page_size))
        if not 200 <= page_status < 300:
            break
        page_items = _deployment_items(page_result)
        if not page_items:
            break
        all_items.extend(page_items)
        page += 1

    merged = dict(result) if isinstance(result, dict) else {}
    merged["items"] = all_items
    merged["total"] = total
    return status, merged


def list_deployments(payload: dict) -> dict:
    valid, message = validate_deploy_envelope(payload, "list")
    if not valid:
        return _response_envelope(payload, {"error": message}, 400, message, -1)

    if not Config.DCE_API_BASE:
        msg = "PaaS 地址未配置"
        return _response_envelope(payload, {"error": "DCE_API_BASE is not configured"}, 500, msg, -1)
    if not Config.DCE_TOKEN:
        msg = "PaaS token 未配置"
        return _response_envelope(payload, {"error": "DCE_TOKEN is not configured"}, 500, msg, -1)

    try:
        client = PaasClient(Config.DCE_API_BASE, Config.DCE_TOKEN)
        deploy_status, deploy_result = _list_namespace_deployments(client)
        if not 200 <= deploy_status < 300:
            msg = "部署列表查询超时" if deploy_status == 504 else "部署列表查询失败"
            return _response_envelope(
                payload,
                {"response": deploy_result},
                deploy_status,
                msg,
                -1,
            )

        records = {
            row.get("deployment_name"): row
            for row in repository.list_deploy_instances()
            if row.get("deployment_name")
        }
        pod_summaries = {}
        pod_path = f"/clusters/{Config.DCE_CLUSTER}/namespaces/{Config.DCE_NAMESPACE}/pods"
        pod_status, pod_result = client.request_with_status("GET", pod_path)
        if pod_status == 200:
            for pod in pod_items(pod_result):
                if not isinstance(pod, dict):
                    continue
                labels = ((pod.get("metadata", {}) or {}).get("labels", {}) or {})
                app_name = labels.get("app")
                if not app_name:
                    continue
                pod_summaries.setdefault(app_name, []).append(summarize_pod(pod))

        items = []
        for raw_deployment in _deployment_items(deploy_result):
            if not isinstance(raw_deployment, dict):
                continue
            deployment = summarize_deployment(raw_deployment)
            deployment_name = deployment.get("name")
            if not deployment_name:
                continue
            record = records.get(deployment_name, {})
            items.append({
                "instance_name": record.get("instance_name") or deployment_name,
                "deployment_name": deployment_name,
                "status": _deployment_display_status(deployment, record, pod_summaries.get(deployment_name, [])),
                "created_at": _format_list_created_at(deployment.get("created_at") or record.get("created_at")),
            })

        items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return _response_envelope(payload, {"items": items}, 200, "OK", 0)
    except Exception as exc:
        msg = "部署列表查询异常"
        return _response_envelope(payload, {"error": str(exc)}, 500, msg, -1)

