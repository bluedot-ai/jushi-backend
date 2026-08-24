"""Pure Kubernetes quantity, node-label, and resource-map parsing helpers."""

import os

from .constants import (
    GPU_CORE_KEYS,
    GPU_MEMORY_KEYS,
    PHYSICAL_GPU_KEYS,
    UNKNOWN_GPU_MODEL,
    VGPU_KEYS,
)
from .settings import _gpu_card_compute_units, _gpu_card_memory_gib, _vgpu_per_gpu


def _estimated_card_count(physical_gpu_total, vgpu_total):
    """
    优先使用真实物理卡数量。
    如果物理卡数量没有返回，但有 vGPU，则按 VGPU_PER_GPU 估算物理卡数量。
    """
    physical_gpu_total = int(physical_gpu_total or 0)
    vgpu_total = int(vgpu_total or 0)

    if physical_gpu_total > 0:
        return physical_gpu_total

    if vgpu_total > 0:
        per_gpu = _vgpu_per_gpu()
        return max(int((vgpu_total + per_gpu - 1) / per_gpu), 1)

    return 0


def _allocation_ratio(physical_gpu_used, physical_gpu_total, vgpu_used, vgpu_total):
    """
    用于估算显存/算力分配率。
    优先参考物理卡分配率，同时兼容 vGPU 分配率。
    """
    ratios = []

    if physical_gpu_total:
        ratios.append(physical_gpu_used / physical_gpu_total)

    if vgpu_total:
        ratios.append(vgpu_used / vgpu_total)

    if not ratios:
        return 0

    return min(max(max(ratios), 0), 1)


def _round2(value):
    value = round(float(value or 0), 2)
    return int(value) if value.is_integer() else value


def _split_value(value, count):
    if not count:
        return 0
    return _round2((value or 0) / count)


def _safe_get(obj, *keys, default=None):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


def _extract_items(result):
    if not isinstance(result, dict):
        return []

    candidates = [
        result.get("items"),
        _safe_get(result, "data", "items"),
        _safe_get(result, "content", "items"),
        _safe_get(result, "response", "items"),
    ]

    for items in candidates:
        if isinstance(items, list):
            return items

    return []


def _parse_number(text):
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return 0


def _parse_cpu_m(value):
    if value is None:
        return 0

    text = str(value).strip()
    if not text:
        return 0

    if text.endswith("m"):
        return int(_parse_number(text[:-1]))

    return int(_parse_number(text) * 1000)


def _parse_memory_bytes(value):
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
            return int(_parse_number(text[: -len(suffix)]) * multiplier)

    return int(_parse_number(text))


def _parse_scalar(value):
    if value is None:
        return 0

    text = str(value).strip()
    if not text:
        return 0

    if text.endswith("m"):
        return int(_parse_number(text[:-1]))

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
            return int(_parse_number(text[: -len(suffix)]) * multiplier)

    return int(_parse_number(text))


def _parse_gpumem_mib(value):
    if value is None:
        return 0

    text = str(value).strip()
    if not text:
        return 0

    if text.endswith("Gi"):
        return int(_parse_number(text[:-2]) * 1024)
    if text.endswith("Mi"):
        return int(_parse_number(text[:-2]))
    if text.endswith("G"):
        return int(_parse_number(text[:-1]) * 1000 / 1024)
    if text.endswith("M"):
        return int(_parse_number(text[:-1]) * 1000 * 1000 / 1024 / 1024)

    # HAMI 的 nvidia.com/gpumem 常见是纯数字，按 MiB 处理。
    return int(_parse_number(text))


def _parse_resource(key, value):
    if key == "cpu":
        return _parse_cpu_m(value)
    if key == "memory":
        return _parse_memory_bytes(value)
    if key == "nvidia.com/gpumem":
        return _parse_gpumem_mib(value)
    return _parse_scalar(value)


def _resource_get(resource_map, key):
    value = (resource_map or {}).get(key)
    if isinstance(value, (int, float)):
        return int(value)
    return _parse_resource(key, value)


def _percent(used, total):
    if not total:
        return 0
    return round(used * 100 / total)


def _bytes_to_gib(value):
    return round(value / 1024 ** 3, 2)


def _mib_to_gib(value):
    return round(value / 1024, 2)


def _sum_resources(resource_map, keys):
    total = 0
    for key in keys:
        total += _resource_get(resource_map, key)
    return total


def _first_existing(resource_map, keys):
    resource_map = resource_map or {}
    for key in keys:
        if key in resource_map:
            return key, _resource_get(resource_map, key)
    return "", 0


def _health_level(percent):
    if percent >= 90:
        return "red"
    if percent >= 70:
        return "yellow"
    return "green"


def _health_text(level):
    return {
        "green": "绿色",
        "yellow": "黄色",
        "red": "红色",
    }.get(level, "未知")


def _add_resource(target, key, value):
    parsed = value if isinstance(value, (int, float)) else _parse_resource(key, value)
    if parsed <= 0:
        return
    target[key] = target.get(key, 0) + parsed


def _merge_resource_totals(primary, fallback):
    """
    primary 通常来自 PaaS resourceSummary。
    fallback 通常来自 K8S Node / Pod 资源反推。
    规则：primary 有值优先；primary 没有或为 0 时，用 fallback 补齐。
    """
    merged = dict(primary or {})
    fallback = fallback or {}

    for key, value in fallback.items():
        if _resource_get(merged, key) <= 0:
            merged[key] = value

    return merged


def _merge_cluster_resource_totals(primary, fallback, allocated=False):
    """
    集群汇总合并规则。

    对 GPU 相关字段：
    - allocatable：优先使用节点聚合值，因为节点 label 能识别 vGPU 节点底层物理卡。
    - allocated：取 PaaS 与 Pod 聚合中的较大值，避免漏算。

    对 CPU / 内存：
    - 保持原逻辑，primary 有值优先。
    """
    merged = dict(primary or {})
    fallback = fallback or {}

    gpu_related_keys = set(PHYSICAL_GPU_KEYS + VGPU_KEYS + GPU_MEMORY_KEYS + GPU_CORE_KEYS)

    for key, value in fallback.items():
        fallback_value = _resource_get(fallback, key)
        current_value = _resource_get(merged, key)

        if key in gpu_related_keys:
            if allocated:
                if max(current_value, fallback_value) > 0:
                    merged[key] = max(current_value, fallback_value)
            else:
                if fallback_value > 0:
                    merged[key] = fallback_value
                elif current_value <= 0:
                    merged[key] = value
        else:
            if current_value <= 0:
                merged[key] = value

    return merged


def _node_name(node):
    return _safe_get(node, "metadata", "name", default="") or node.get("name") or ""


def _node_labels(node):
    return _safe_get(node, "metadata", "labels", default={}) or {}


def _node_capacity(node):
    return _safe_get(node, "status", "capacity", default={}) or {}


def _to_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _normalize_gpu_model(value):
    if not value:
        return UNKNOWN_GPU_MODEL

    text = str(value).strip()
    text = text.replace("_", " ").replace("-", " ")

    # NVIDIA-A10 -> NVIDIA A10
    text = " ".join(text.split())
    return text


def _node_gpu_mode(node):
    labels = _node_labels(node)

    mode = str(labels.get("gpu.node.kpanda.io/nvidia-gpu-mode") or "").lower()
    vendor = str(labels.get("node.kpanda.io/gpu-vendor") or "").lower()
    vgpu_plugin = str(labels.get("nvidia.com/vgpu.deploy.device-plugin") or "").lower()

    if mode == "vgpu" or "vgpu" in vendor or vgpu_plugin == "true":
        return "vgpu"

    if mode == "gpu" or "nvidia-gpu" in vendor:
        return "gpu"

    allocatable = _node_base_allocatable(node)
    if _resource_get(allocatable, "nvidia.com/vgpu") > 0:
        return "vgpu"

    if _resource_get(allocatable, "nvidia.com/gpu") > 0:
        return "gpu"

    return "unknown"


def _node_gpu_vendor(node):
    labels = _node_labels(node)
    return labels.get("node.kpanda.io/gpu-vendor") or ""


def _node_gpu_product(node):
    labels = _node_labels(node)

    value = (
        labels.get("nvidia.com/gpu.product")
        or labels.get("gpu.nvidia.com/model")
        or labels.get("gpu.product")
        or labels.get("accelerator")
        or ""
    )

    if value:
        return _normalize_gpu_model(value)

    return UNKNOWN_GPU_MODEL


def _node_gpu_label_count(node):
    labels = _node_labels(node)
    return _to_int(labels.get("nvidia.com/gpu.count"), 0)


def _node_gpu_memory_mib_per_card(node):
    labels = _node_labels(node)

    # 青海节点 label: nvidia.com/gpu.memory=23028，单位按 MiB 处理。
    label_memory = _to_int(labels.get("nvidia.com/gpu.memory"), 0)
    if label_memory > 0:
        return label_memory

    # 兜底用环境变量，默认 A10 24GiB。
    return int(_gpu_card_memory_gib() * 1024)


def _node_gpu_physical_count(node, allocatable=None):
    allocatable = allocatable or _node_base_allocatable(node)

    label_count = _node_gpu_label_count(node)
    gpu_count = _resource_get(allocatable, "nvidia.com/gpu")
    if label_count > 0 or gpu_count > 0:
        return max(label_count, gpu_count)

    vgpu_count = _resource_get(allocatable, "nvidia.com/vgpu")
    if vgpu_count > 0:
        return _estimated_card_count(0, vgpu_count)

    return 0


def _node_gpu_core_total(node, physical_count):
    if physical_count <= 0:
        return 0
    return int(physical_count * _gpu_card_compute_units())


def _node_gpu_mem_total_mib(node, physical_count):
    if physical_count <= 0:
        return 0
    return int(physical_count * _node_gpu_memory_mib_per_card(node))


def _node_vgpu_per_gpu(node, physical_count, vgpu_total):
    if physical_count <= 0 or vgpu_total <= 0:
        return 0
    return round(vgpu_total / physical_count, 2)


def _node_base_allocatable(node):
    return (
        _safe_get(node, "status", "allocatable")
        or _safe_get(node, "status", "capacity")
        or _safe_get(node, "status", "resourceSummary", "allocatable")
        or {}
    )


def _enhance_node_allocatable(node, allocatable=None):
    """
    将节点 label 中的 GPU 信息补进 allocatable。

    青海场景：
    qhvgpu1:
      nvidia.com/gpu=4
      nvidia.com/vgpu=0
      nvidia.com/gpu.count=4

    qhvgpu2:
      nvidia.com/gpu=0
      nvidia.com/vgpu=40
      nvidia.com/gpu.count=4

    这里需要把 qhvgpu2 的底层 4 张物理卡也纳入 physical_gpu_total。
    这一步是资源中心展示“显卡张数”的关键：PaaS/K8s 可能只暴露 vGPU，
    但产品页面仍然希望看到底层物理卡容量。
    """
    base = dict(allocatable or _node_base_allocatable(node))

    physical_count = _node_gpu_physical_count(node, base)
    vgpu_total = _resource_get(base, "nvidia.com/vgpu")

    if physical_count > 0:
        # gpu_total 代表底层物理卡数量。vgpu 节点也要计入。
        base["nvidia.com/gpu"] = str(physical_count)

        # 根据节点 label 自动计算显存容量。
        gpu_mem_total_mib = _node_gpu_mem_total_mib(node, physical_count)
        if gpu_mem_total_mib > 0:
            base["nvidia.com/gpumem"] = str(gpu_mem_total_mib)

        # 算力暂时使用标准化容量单位。
        gpu_core_total = _node_gpu_core_total(node, physical_count)
        if gpu_core_total > 0:
            base["nvidia.com/gpucores"] = str(gpu_core_total)

    if vgpu_total > 0:
        base["nvidia.com/vgpu"] = str(vgpu_total)

    return base


def _node_allocatable(node):
    return _enhance_node_allocatable(node, _node_base_allocatable(node))


def _node_allocated_from_paas(node):
    return (
        _safe_get(node, "status", "resourceSummary", "allocated")
        or _safe_get(node, "status", "allocated")
        or {}
    )


def _pod_phase(pod):
    return _safe_get(pod, "status", "phase", default="Unknown")


def _pod_node_name(pod):
    return _safe_get(pod, "spec", "nodeName", default="")


def _pod_resources(pod):
    result = {}

    if _pod_phase(pod) in {"Succeeded", "Failed"}:
        return result

    containers = _safe_get(pod, "spec", "containers", default=[]) or []
    for container in containers:
        resources = container.get("resources") or {}
        merged = dict(resources.get("requests") or {})
        merged.update(resources.get("limits") or {})

        for key, value in merged.items():
            _add_resource(result, key, value)

    return result


def _gpu_model_node_map():
    """
    可选配置：
    GPU_MODEL_NODE_MAP='{"node-gpu-01":"NVIDIA T4","node-gpu-02":"NVIDIA A100"}'

    用于节点 label 不完整时，人工补齐显卡型号展示。
    """
    raw = os.getenv("GPU_MODEL_NODE_MAP") or ""
    if not raw.strip():
        return {}

    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _extract_gpu_model(node):
    product = _node_gpu_product(node)
    if product != UNKNOWN_GPU_MODEL:
        return product

    labels = _node_labels(node)
    capacity = _node_capacity(node)
    allocatable = _node_allocatable(node)

    candidate_keys = [
        "nvidia.com/gpu.product",
        "gpu.nvidia.com/model",
        "gpu.product",
        "accelerator",
        "hami.io/vgpu-devices-to-allocate",
        "huawei.com/ascend.product",
        "huawei.com/npu.product",
    ]

    for key in candidate_keys:
        value = labels.get(key)
        if value:
            return _normalize_gpu_model(value)

    if _parse_resource(
        "huawei.com/Ascend310P",
        capacity.get("huawei.com/Ascend310P") or allocatable.get("huawei.com/Ascend310P"),
    ):
        return "Ascend 310P"

    if _parse_resource(
        "nvidia.com/vgpu",
        capacity.get("nvidia.com/vgpu") or allocatable.get("nvidia.com/vgpu"),
    ):
        return "NVIDIA vGPU"

    if _parse_resource(
        "nvidia.com/gpu",
        capacity.get("nvidia.com/gpu") or allocatable.get("nvidia.com/gpu"),
    ):
        return "NVIDIA GPU"

    return UNKNOWN_GPU_MODEL


def _node_status(node):
    conditions = _safe_get(node, "status", "conditions", default=[]) or []
    for condition in conditions:
        if condition.get("type") == "Ready":
            return "Ready" if condition.get("status") == "True" else "NotReady"
    return _safe_get(node, "status", "phase", default="Unknown")


def _node_schedulable(node):
    return _node_status(node) == "Ready" and not bool(
        _safe_get(node, "spec", "unschedulable", default=False)
    )

