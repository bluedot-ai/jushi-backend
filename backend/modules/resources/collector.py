"""PaaS and Kubernetes collection for the resources module."""

try:
    from backend.config import Config
    from backend.services.paas_client import PaasClient
    from backend.services.k8s_client import K8sClient
except ModuleNotFoundError:
    from config import Config
    from services.paas_client import PaasClient
    from services.k8s_client import K8sClient

from .constants import METRIC_SOURCE
from .parser import (
    _add_resource,
    _extract_items,
    _merge_cluster_resource_totals,
    _merge_resource_totals,
    _node_allocatable,
    _node_allocated_from_paas,
    _node_gpu_physical_count,
    _node_name,
    _pod_node_name,
    _pod_resources,
    _safe_get,
)
from .response import _error, _now, _ok


def _paas_client():
    # PaaS/DCE 是资源中心最主要的数据入口；没有平台地址或 token 时资源接口不能工作。
    if not Config.DCE_API_BASE:
        return None, _error("DCE_API_BASE is not configured", 500)
    if not Config.DCE_TOKEN:
        return None, _error("DCE_TOKEN is not configured", 500)
    return PaasClient(Config.DCE_API_BASE, Config.DCE_TOKEN), None


def _k8s_client():
    # Kubernetes 原生 API 用作补充入口，主要查 nodes、pods、resourcequotas 等 PaaS 包装不稳定的对象。
    client = K8sClient.from_config(Config)
    if not client.api_base:
        return None, _error("K8S_API_BASE is not configured", 500)
    if not client.token:
        return None, _error("K8S_TOKEN is not configured", 500)
    return client, None


def _get_resource_summary_from_cluster(cluster):
    candidates = [
        _safe_get(cluster, "status", "resourceSummary"),
        _safe_get(cluster, "data", "status", "resourceSummary"),
        _safe_get(cluster, "content", "status", "resourceSummary"),
        _safe_get(cluster, "response", "status", "resourceSummary"),
    ]

    for item in candidates:
        if isinstance(item, dict):
            return item.get("allocatable") or {}, item.get("allocated") or {}

    return {}, {}


def _get_cluster_resource_summary():
    # 读取 PaaS 集群资源汇总，相当于“全局资源池”的粗粒度总账。
    client, err = _paas_client()
    if err:
        return None, err

    status, result = client.request_with_status("GET", f"/clusters/{Config.DCE_CLUSTER}")
    if not 200 <= status < 300:
        return None, _error("Failed to query cluster resource summary", status, result)

    allocatable, allocated = _get_resource_summary_from_cluster(result)

    return {
        "client": client,
        "cluster": result,
        "allocatable": allocatable,
        "allocated": allocated,
    }, None

def _list_nodes_from_paas(client):
    status, result = client.request_with_status("GET", f"/clusters/{Config.DCE_CLUSTER}/nodes")
    if not 200 <= status < 300:
        return None, _error("Failed to query PaaS node list", status, result)

    return _extract_items(result), None


def _list_nodes_from_k8s():
    client, err = _k8s_client()
    if err:
        return None, err

    status, result = client._request("GET", "/api/v1/nodes")
    if not 200 <= status < 300:
        return None, _error("Failed to query Kubernetes node list", status, result)

    return _extract_items(result), None


def _list_nodes(client):
    # 节点容量以 Kubernetes 原生 Node 为准；PaaS 节点明细在部分环境中可能滞后或裁剪 GPU 字段。
    k8s_nodes, k8s_error = _list_nodes_from_k8s()
    if k8s_nodes is not None:
        return k8s_nodes, None

    paas_nodes, paas_error = _list_nodes_from_paas(client)
    if paas_nodes:
        return paas_nodes, None

    return [], {
        "k8s_error": k8s_error,
        "paas_error": paas_error,
    }


def _list_namespace_pods(namespace):
    """
    资源统计要看全局 Pod，而不是只看 DCE_NAMESPACE。

    原因：
    1. 青海环境 GPU 工作负载分布在 algorithm / default / cigaretee / yolo / test1 等多个 namespace。
    2. 如果只查 algorithm，会把 qhvgpu1 的 GPU 使用量算成 1/4，也就是 25%。
    3. 真实资源分配口径应该基于全 namespace Running Pod 聚合。

    如果 service account 没有 list cluster pods 权限，则降级为当前 namespace。
    """
    client, err = _k8s_client()
    if err:
        return [], err

    status, result = client.list_cluster_pods()
    if 200 <= status < 300:
        return _extract_items(result), None

    fallback_status, fallback_result = client.list_pods(namespace)
    if not 200 <= fallback_status < 300:
        return [], _error("Failed to query pod list", fallback_status, {
            "cluster_pods_error": result,
            "namespace_pods_error": fallback_result,
        })

    return _extract_items(fallback_result), {
        "warning": "No permission to list cluster pods. Fallback to namespace pods.",
        "cluster_pods_error": result,
    }

def _allocated_by_node_from_pods(pods):
    # 通过全命名空间 Pod 的 requests/limits 反推每个节点的已分配资源。
    # 这是 PaaS allocated 不完整时的兜底口径，也是资源预检和资源中心一致性的基础。
    by_node = {}

    for pod in pods:
        node_name = _pod_node_name(pod)
        if not node_name:
            continue

        pod_resource = _pod_resources(pod)
        if not pod_resource:
            continue

        by_node.setdefault(node_name, {})
        for key, value in pod_resource.items():
            by_node[node_name][key] = by_node[node_name].get(key, 0) + value

    return by_node


def _aggregate_node_resources(raw_nodes, pod_allocated_by_node):
    # 汇总所有节点的 allocatable / allocated。
    # allocatable 侧会结合节点 label 增强 GPU/vGPU 信息；allocated 侧会合并 PaaS 和 Pod 反推结果。
    allocatable_total = {}
    allocated_total = {}
    physical_gpu_total = 0

    for node in raw_nodes:
        node_name = _node_name(node)
        allocatable = _node_allocatable(node)
        allocated = _merge_resource_totals(
            _node_allocated_from_paas(node),
            pod_allocated_by_node.get(node_name, {}),
        )

        for key, value in allocatable.items():
            _add_resource(allocatable_total, key, value)

        for key, value in allocated.items():
            _add_resource(allocated_total, key, value)

        # 物理卡数量统一用 _node_gpu_physical_count，与节点行展示口径一致
        physical_gpu_total += _node_gpu_physical_count(node, allocatable)

    # 用显式累加的物理卡数覆盖 allocatable 中可能不一致的 nvidia.com/gpu
    if physical_gpu_total > 0:
        allocatable_total["nvidia.com/gpu"] = physical_gpu_total

    return allocatable_total, allocated_total

def _resource_context(query):
    # resources 模块的核心上下文构建函数。
    # 对外的 summary / nodes / gpus / cards / recommendation 基本都先走这里，
    # 再把同一份底层资源快照转换成不同页面需要的视图。
    snapshot, err = _get_cluster_resource_summary()
    if err:
        return None, err

    client = snapshot["client"]
    namespace = query.get("namespace") or Config.DCE_NAMESPACE
    collected_at = _now()

    raw_nodes, nodes_error = _list_nodes(client)
    pods, pod_error = _list_namespace_pods(namespace)
    pod_allocated_by_node = _allocated_by_node_from_pods(pods)

    node_allocatable_total, node_allocated_total = _aggregate_node_resources(
        raw_nodes,
        pod_allocated_by_node,
    )

    return {
        "client": client,
        "namespace": namespace,
        "cluster": snapshot["cluster"],
        "raw_nodes": raw_nodes,
        "pods": pods,
        "pod_allocated_by_node": pod_allocated_by_node,
        "allocatable": _merge_cluster_resource_totals(
            snapshot["allocatable"],
            node_allocatable_total,
            allocated=False,
        ),
        "allocated": _merge_cluster_resource_totals(
            snapshot["allocated"],
            node_allocated_total,
            allocated=True,
        ),
        "collected_at": collected_at,
        "metric_source": METRIC_SOURCE,
        "diagnostics": {
            "nodes_error": nodes_error,
            "pod_error": pod_error,
            "resource_source": METRIC_SOURCE,
            "usage_metric_ready": False,
            "usage_metric_source": "not_configured",
        },
    }, None

def quotas(query):
    # 命名空间 ResourceQuota 查询。无权限或没有配置 quota 时降级返回空列表，不阻塞资源中心页面。
    client, err = _k8s_client()
    if err:
        return err

    namespace = query.get("namespace") or Config.DCE_NAMESPACE
    status, result = client._request("GET", f"/api/v1/namespaces/{namespace}/resourcequotas")

    if status == 403:
        return _ok({
            "namespace": namespace,
            "items": [],
            "total": 0,
            "warning": "Current service account has no permission to list ResourceQuota. Quota display is skipped.",
            "permission_required": {
                "api_group": "",
                "resource": "resourcequotas",
                "verb": "list",
                "namespace": namespace,
            },
            "response": result,
        })

    if status == 404:
        return _ok({
            "namespace": namespace,
            "items": [],
            "total": 0,
            "warning": "ResourceQuota is not configured in the namespace.",
            "response": result,
        })

    if not 200 <= status < 300:
        return _error("Failed to query ResourceQuota", status, result)

    items = []
    for item in result.get("items", []) or []:
        metadata = item.get("metadata") or {}
        status_obj = item.get("status") or {}

        items.append({
            "name": metadata.get("name"),
            "namespace": metadata.get("namespace"),
            "hard": status_obj.get("hard") or {},
            "used": status_obj.get("used") or {},
        })

    return _ok({
        "namespace": namespace,
        "items": items,
        "total": len(items),
    })

