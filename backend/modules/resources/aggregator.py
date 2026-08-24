"""Pure resource aggregation and resource-card construction."""

from .constants import (
    GPU_CORE_KEYS,
    GPU_MEMORY_KEYS,
    METRIC_SOURCE,
    PHYSICAL_GPU_KEYS,
    PROMETHEUS_METRIC_SOURCE,
    VGPU_KEYS,
)
from .metrics import _apply_prometheus_memory_to_cards, _prometheus_gpu_memory_by_node
from .parser import (
    _allocation_ratio,
    _bytes_to_gib,
    _estimated_card_count,
    _first_existing,
    _merge_resource_totals,
    _mib_to_gib,
    _node_allocatable,
    _node_allocated_from_paas,
    _node_name,
    _parse_cpu_m,
    _parse_memory_bytes,
    _percent,
    _resource_get,
    _sum_resources,
)
from .settings import (
    _capacity_estimation_enabled,
    _gpu_card_compute_units,
    _gpu_card_memory_gib,
    _vgpu_per_gpu,
)


def _node_card_rows(context):
    """Build node-level resource cards with the same logic used by /resources/nodes."""
    rows = []
    memory_by_node, memory_error = _prometheus_gpu_memory_by_node()
    context["prometheus_gpu_memory_error"] = memory_error
    context["prometheus_gpu_memory_ready"] = bool(memory_by_node)
    for node in context["raw_nodes"]:
        node_name = _node_name(node)
        allocatable = _node_allocatable(node)
        allocated = _merge_resource_totals(
            _node_allocated_from_paas(node),
            context["pod_allocated_by_node"].get(node_name, {}),
        )
        cards = _resource_summary_cards(allocatable, allocated)
        cards = _apply_prometheus_memory_to_cards(cards, memory_by_node.get(node_name))
        rows.append({
            "node": node,
            "node_name": node_name,
            "allocatable": allocatable,
            "allocated": allocated,
            "cards": cards,
        })
    return rows

def _apply_node_level_card_totals(cards, node_rows):
    """
    Align summary cards with the node detail list.

    PaaS cluster resourceSummary can expose GPU count and GPU memory with different
    scopes. The top cards should use the same node-level aggregation as the
    "节点显存采集明细" panel so users see one consistent resource view.
    """
    if not node_rows:
        return cards

    node_cards = [row["cards"] for row in node_rows]

    physical_gpu_total = sum(card.get("physical_gpu_total", 0) for card in node_cards)
    physical_gpu_used = sum(card.get("physical_gpu_used", 0) for card in node_cards)
    vgpu_total = sum(card.get("vgpu_total", 0) for card in node_cards)
    vgpu_used = sum(card.get("vgpu_used", 0) for card in node_cards)

    gpu_mem_total_gib = round(sum(card.get("gpu_mem_total_gib", 0) for card in node_cards), 2)
    gpu_mem_used_gib = round(sum(card.get("gpu_mem_used_gib", 0) for card in node_cards), 2)
    gpu_core_total = sum(card.get("gpu_core_total", 0) for card in node_cards)
    gpu_core_used = sum(card.get("gpu_core_used", 0) for card in node_cards)
    usage_metric_ready = any(card.get("usage_metric_ready") for card in node_cards)
    usage_metric_source = (
        PROMETHEUS_METRIC_SOURCE
        if usage_metric_ready
        else cards.get("usage_metric_source", "not_configured")
    )

    cards.update({
        "gpu_total": physical_gpu_total,
        "gpu_used": physical_gpu_used,
        "gpu_available": max(physical_gpu_total - physical_gpu_used, 0),
        "gpu_alloc_percent": _percent(physical_gpu_used, physical_gpu_total),

        "physical_gpu_total": physical_gpu_total,
        "physical_gpu_used": physical_gpu_used,
        "physical_gpu_available": max(physical_gpu_total - physical_gpu_used, 0),
        "physical_gpu_alloc_percent": _percent(physical_gpu_used, physical_gpu_total),

        "vgpu_total": vgpu_total,
        "vgpu_used": vgpu_used,
        "vgpu_available": max(vgpu_total - vgpu_used, 0),
        "vgpu_alloc_percent": _percent(vgpu_used, vgpu_total),

        "accelerator_unit_total": physical_gpu_total + vgpu_total,
        "accelerator_unit_used": physical_gpu_used + vgpu_used,

        "gpu_mem_total_gib": gpu_mem_total_gib,
        "gpu_mem_used_gib": gpu_mem_used_gib,
        "gpu_mem_alloc_percent": _percent(gpu_mem_used_gib, gpu_mem_total_gib),
        "gpu_mem_percent": _percent(gpu_mem_used_gib, gpu_mem_total_gib),
        "gpu_mem_usage_percent": (
            _percent(gpu_mem_used_gib, gpu_mem_total_gib)
            if usage_metric_ready
            else cards.get("gpu_mem_usage_percent")
        ),

        "gpu_core_total": gpu_core_total,
        "gpu_core_used": gpu_core_used,
        "gpu_core_alloc_percent": _percent(gpu_core_used, gpu_core_total),
        "gpu_core_percent": _percent(gpu_core_used, gpu_core_total),

        "capacity_estimated": cards.get("capacity_estimated") or any(
            card.get("capacity_estimated") for card in node_cards
        ),
        "gpu_mem_capacity_estimated": any(
            card.get("gpu_mem_capacity_estimated") for card in node_cards
        ),
        "gpu_core_capacity_estimated": any(
            card.get("gpu_core_capacity_estimated") for card in node_cards
        ),
        "usage_metric_ready": usage_metric_ready,
        "usage_metric_source": usage_metric_source,
        "allocation_metric_source": "node_level_resource_cards",
        "summary_metric_source": "node_level_resource_cards",
    })

    return cards

def _resource_summary_cards(allocatable, allocated):
    # 把底层资源 map 转成前端卡片所需字段。
    # 注意：显存/算力如果没有平台原生资源键，会按环境变量估算容量和已分配量。
    physical_gpu_total = _sum_resources(allocatable, PHYSICAL_GPU_KEYS)
    physical_gpu_used = _sum_resources(allocated, PHYSICAL_GPU_KEYS)

    vgpu_total = _sum_resources(allocatable, VGPU_KEYS)
    vgpu_used = _sum_resources(allocated, VGPU_KEYS)

    estimated_card_count = _estimated_card_count(physical_gpu_total, vgpu_total)

    gpu_mem_key, gpu_mem_total_mib = _first_existing(allocatable, GPU_MEMORY_KEYS)
    gpu_mem_used_mib = _resource_get(allocated, gpu_mem_key) if gpu_mem_key else 0

    gpu_core_key, gpu_core_total = _first_existing(allocatable, GPU_CORE_KEYS)
    gpu_core_used = _resource_get(allocated, gpu_core_key) if gpu_core_key else 0

    capacity_estimated = False
    gpu_mem_capacity_estimated = False
    gpu_core_capacity_estimated = False

    ratio = _allocation_ratio(
        physical_gpu_used,
        physical_gpu_total,
        vgpu_used,
        vgpu_total,
    )

    # 没有显存总量时，按环境变量估算总量。
    if gpu_mem_total_mib <= 0 and _capacity_estimation_enabled() and estimated_card_count > 0:
        gpu_mem_total_mib = int(estimated_card_count * _gpu_card_memory_gib() * 1024)
        capacity_estimated = True
        gpu_mem_capacity_estimated = True

    # 有显存总量但没有显存分配量时，按物理卡 / vGPU 分配比例估算已分配显存。
    if gpu_mem_total_mib > 0 and gpu_mem_used_mib <= 0 and ratio > 0:
        gpu_mem_used_mib = int(gpu_mem_total_mib * ratio)
        capacity_estimated = True
        gpu_mem_capacity_estimated = True

    # 没有算力总量时，按物理卡数量估算标准化算力容量。
    if gpu_core_total <= 0 and _capacity_estimation_enabled() and estimated_card_count > 0:
        gpu_core_total = int(estimated_card_count * _gpu_card_compute_units())
        capacity_estimated = True
        gpu_core_capacity_estimated = True

    # 有算力总量但没有算力分配量时，按资源分配比例估算。
    if gpu_core_total > 0 and gpu_core_used <= 0 and ratio > 0:
        gpu_core_used = int(gpu_core_total * ratio)
        capacity_estimated = True
        gpu_core_capacity_estimated = True

    cpu_total_m = _parse_cpu_m(allocatable.get("cpu"))
    cpu_used_m = _resource_get(allocated, "cpu")

    memory_total_bytes = _parse_memory_bytes(allocatable.get("memory"))
    memory_used_bytes = _resource_get(allocated, "memory")

    gpu_core_alloc_percent = _percent(gpu_core_used, gpu_core_total)
    gpu_mem_alloc_percent = _percent(gpu_mem_used_mib, gpu_mem_total_mib)

    return {
        "gpu_total": physical_gpu_total,
        "gpu_used": physical_gpu_used,
        "gpu_available": max(physical_gpu_total - physical_gpu_used, 0),
        "gpu_alloc_percent": _percent(physical_gpu_used, physical_gpu_total),

        "physical_gpu_total": physical_gpu_total,
        "physical_gpu_used": physical_gpu_used,
        "physical_gpu_available": max(physical_gpu_total - physical_gpu_used, 0),
        "physical_gpu_alloc_percent": _percent(physical_gpu_used, physical_gpu_total),

        "vgpu_total": vgpu_total,
        "vgpu_used": vgpu_used,
        "vgpu_available": max(vgpu_total - vgpu_used, 0),
        "vgpu_alloc_percent": _percent(vgpu_used, vgpu_total),

        "accelerator_unit_total": physical_gpu_total + vgpu_total,
        "accelerator_unit_used": physical_gpu_used + vgpu_used,

        "gpu_core_total": gpu_core_total,
        "gpu_core_used": gpu_core_used,
        "gpu_core_alloc_percent": gpu_core_alloc_percent,
        "gpu_core_percent": gpu_core_alloc_percent,
        "gpu_core_usage_percent": None,
        "gpu_core_capacity_estimated": gpu_core_capacity_estimated,

        "gpu_mem_total_gib": _mib_to_gib(gpu_mem_total_mib),
        "gpu_mem_used_gib": _mib_to_gib(gpu_mem_used_mib),
        "gpu_mem_alloc_percent": gpu_mem_alloc_percent,
        "gpu_mem_percent": gpu_mem_alloc_percent,
        "gpu_mem_usage_percent": None,
        "gpu_mem_capacity_estimated": gpu_mem_capacity_estimated,

        "cpu_total_m": cpu_total_m,
        "cpu_used_m": cpu_used_m,
        "cpu_percent": _percent(cpu_used_m, cpu_total_m),

        "memory_total_gib": _bytes_to_gib(memory_total_bytes),
        "memory_used_gib": _bytes_to_gib(memory_used_bytes),
        "memory_percent": _percent(memory_used_bytes, memory_total_bytes),

        "usage_metric_ready": False,
        "usage_metric_source": "not_configured",
        "allocation_metric_source": METRIC_SOURCE,

        "capacity_estimated": capacity_estimated,
        "capacity_estimation_source": (
            "node_label_or_ratio"
            if capacity_estimated
            else "resource_key"
        ),
        "capacity_estimation_config": {
            "enabled": _capacity_estimation_enabled(),
            "gpu_card_memory_gib": _gpu_card_memory_gib(),
            "gpu_card_compute_units": _gpu_card_compute_units(),
            "vgpu_per_gpu": _vgpu_per_gpu(),
        },
    }

