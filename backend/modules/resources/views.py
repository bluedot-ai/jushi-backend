"""Resource summary, node, GPU, and card view builders."""

try:
    from backend.config import Config
except ModuleNotFoundError:
    from config import Config

from .aggregator import _apply_node_level_card_totals, _node_card_rows, _resource_summary_cards
from .collector import _resource_context
from .constants import GPU_RESOURCE_META, METRIC_SOURCE, PHYSICAL_GPU_KEYS, UNKNOWN_GPU_MODEL
from .parser import (
    _estimated_card_count,
    _extract_gpu_model,
    _gpu_model_node_map,
    _health_level,
    _health_text,
    _mib_to_gib,
    _node_allocatable,
    _node_gpu_memory_mib_per_card,
    _node_gpu_mode,
    _node_gpu_vendor,
    _node_name,
    _node_schedulable,
    _node_status,
    _node_vgpu_per_gpu,
    _percent,
    _resource_get,
    _split_value,
    _sum_resources,
)
from .repository import _save_resource_snapshot
from .response import _ok
from .settings import _vgpu_per_gpu


def _summary_from_context(context, node_rows=None, *, save_snapshot=True):
    # 资源总览：首页和资源中心顶部统计使用。
    # 这里会顺手写入 resource_snapshot，供 /trend 后续读取历史趋势。
    node_rows = node_rows if node_rows is not None else _node_card_rows(context)
    cards = _resource_summary_cards(context["allocatable"], context["allocated"])
    cards = _apply_node_level_card_totals(cards, node_rows)
    cards["node_count"] = len(context["raw_nodes"])

    max_percent = max(
        cards.get("gpu_alloc_percent", 0),
        cards.get("vgpu_alloc_percent", 0),
        cards.get("gpu_core_alloc_percent", 0),
        cards.get("gpu_mem_alloc_percent", 0),
    )
    level = _health_level(max_percent)
    diagnostics = dict(context["diagnostics"])
    diagnostics.update({
        "usage_metric_ready": cards.get("usage_metric_ready", False),
        "usage_metric_source": cards.get("usage_metric_source", "not_configured"),
        "prometheus_gpu_memory_ready": context.get("prometheus_gpu_memory_ready", False),
        "prometheus_gpu_memory_error": context.get("prometheus_gpu_memory_error"),
    })

    result = _ok({
        "cluster": Config.DCE_CLUSTER,
        "namespace": context["namespace"],
        "collected_at": context["collected_at"],
        "metric_source": context["metric_source"],
        "health": {
            "level": level,
            "text": _health_text(level),
            "score": max(0, 100 - max_percent // 2),
            "message": "资源调度健康" if level == "green" else "部分资源接近高负载",
        },
        "cards": cards,
        "raw_resource_keys": {
            "allocatable": sorted(list((context["allocatable"] or {}).keys())),
            "allocated": sorted(list((context["allocated"] or {}).keys())),
        },
        "diagnostics": diagnostics,
    })

    if save_snapshot:
        _save_resource_snapshot("summary", result)

    return result


def summary(query):
    context, err = _resource_context(query)
    if err:
        return err
    return _summary_from_context(context)


def _nodes_from_context(context, query, node_rows=None):
    # 节点资源列表：按节点展示 GPU/vGPU/显存/算力/CPU/内存等分配情况。
    # 支持 node_name 查询参数做单节点过滤。
    items = []

    node_rows = node_rows if node_rows is not None else _node_card_rows(context)
    for row in node_rows:
        node = row["node"]
        node_name = row["node_name"]
        allocatable = row["allocatable"]
        allocated = row["allocated"]
        cards = row["cards"]

        max_percent = max(
            cards.get("gpu_alloc_percent", 0),
            cards.get("vgpu_alloc_percent", 0),
            cards.get("gpu_core_alloc_percent", 0),
            cards.get("gpu_mem_alloc_percent", 0),
        )
        level = _health_level(max_percent)

        item = {
            "node_name": node_name,
            "status": _node_status(node),
            "schedulable": _node_schedulable(node),
            "health_level": level,
            "health_text": _health_text(level),
            "gpu_model": _extract_gpu_model(node),
            "collected_at": context["collected_at"],
            "gpu_mode": _node_gpu_mode(node),
            "gpu_vendor": _node_gpu_vendor(node),
            "gpu_memory_mib_per_card": _node_gpu_memory_mib_per_card(node),
            "gpu_memory_gib_per_card": _mib_to_gib(_node_gpu_memory_mib_per_card(node)),
            "vgpu_per_gpu": _node_vgpu_per_gpu(
                node,
                cards.get("physical_gpu_total", 0),
                cards.get("vgpu_total", 0),
            ),
            "metric_source": context["metric_source"],

            "gpu_total": cards["gpu_total"],
            "gpu_used": cards["gpu_used"],
            "gpu_available": cards["gpu_available"],
            "gpu_percent": cards["gpu_alloc_percent"],
            "gpu_alloc_percent": cards["gpu_alloc_percent"],

            "physical_gpu_total": cards["physical_gpu_total"],
            "physical_gpu_used": cards["physical_gpu_used"],
            "physical_gpu_available": cards["physical_gpu_available"],
            "physical_gpu_alloc_percent": cards["physical_gpu_alloc_percent"],

            "vgpu_total": cards["vgpu_total"],
            "vgpu_used": cards["vgpu_used"],
            "vgpu_available": cards["vgpu_available"],
            "vgpu_percent": cards["vgpu_alloc_percent"],
            "vgpu_alloc_percent": cards["vgpu_alloc_percent"],

            "accelerator_unit_total": cards["accelerator_unit_total"],
            "accelerator_unit_used": cards["accelerator_unit_used"],

            "gpu_core_total": cards["gpu_core_total"],
            "gpu_core_used": cards["gpu_core_used"],
            "gpu_core_percent": cards["gpu_core_alloc_percent"],
            "gpu_core_alloc_percent": cards["gpu_core_alloc_percent"],
            "gpu_core_usage_percent": None,
            "gpu_core_capacity_estimated": cards["gpu_core_capacity_estimated"],

            "gpu_mem_total_gib": cards["gpu_mem_total_gib"],
            "gpu_mem_used_gib": cards["gpu_mem_used_gib"],
            "gpu_mem_percent": cards["gpu_mem_alloc_percent"],
            "gpu_mem_alloc_percent": cards["gpu_mem_alloc_percent"],
            "gpu_mem_usage_percent": cards.get("gpu_mem_usage_percent"),
            "gpu_mem_capacity_estimated": cards["gpu_mem_capacity_estimated"],

            "cpu_total_m": cards["cpu_total_m"],
            "cpu_used_m": cards["cpu_used_m"],
            "memory_total_gib": cards["memory_total_gib"],
            "memory_used_gib": cards["memory_used_gib"],

            "usage_metric_ready": cards.get("usage_metric_ready", False),
            "usage_metric_source": cards.get("usage_metric_source", "not_configured"),

            "capacity_estimated": cards["capacity_estimated"],
            "capacity_estimation_source": cards["capacity_estimation_source"],
            "capacity_estimation_config": cards["capacity_estimation_config"],

            "allocatable": {
                key: allocatable.get(key)
                for key in GPU_RESOURCE_META.keys()
                if key in allocatable
            },
            "allocated": {
                key: allocated.get(key)
                for key in GPU_RESOURCE_META.keys()
                if key in allocated
            },
            "diagnostics": {
                "allocated_source": "paas_node_allocated + pod_resource_fallback",
            },
        }

        if query.get("node_name") and query.get("node_name") != item["node_name"]:
            continue

        items.append(item)

    items.sort(
        key=lambda item: max(
            item.get("vgpu_alloc_percent", 0),
            item.get("gpu_alloc_percent", 0),
            item.get("gpu_mem_alloc_percent", 0),
            item.get("gpu_core_alloc_percent", 0),
        ),
        reverse=True,
    )

    diagnostics = dict(context["diagnostics"])
    diagnostics.update({
        "prometheus_gpu_memory_ready": context.get("prometheus_gpu_memory_ready", False),
        "prometheus_gpu_memory_error": context.get("prometheus_gpu_memory_error"),
    })

    return _ok({
        "namespace": context["namespace"],
        "collected_at": context["collected_at"],
        "metric_source": context["metric_source"],
        "items": items,
        "total": len(items),
        "diagnostics": diagnostics,
    })


def nodes(query):
    context, err = _resource_context(query)
    if err:
        return err
    return _nodes_from_context(context, query)


def gpus(query):
    # GPU 统计视图：按资源名和显卡型号聚合，供“显卡类别占比”和 Top 节点展示使用。
    context, err = _resource_context(query)
    if err:
        return err

    resources = []

    for key, meta in GPU_RESOURCE_META.items():
        total = _resource_get(context["allocatable"], key)
        used = _resource_get(context["allocated"], key)

        if total <= 0 and used <= 0:
            continue

        percent = _percent(used, total)
        resources.append({
            "resource_name": key,
            "display_name": meta["display_name"],
            "vendor": meta["vendor"],
            "kind": meta["kind"],
            "unit": meta["unit"],
            "total": total,
            "used": used,
            "available": max(total - used, 0),
            "percent": percent,
            "alloc_percent": percent,
            "usage_percent": None,
            "usage_metric_ready": False,
        })

    model_map = {}
    unknown_nodes = []

    for node in context["raw_nodes"]:
        model = _extract_gpu_model(node)
        allocatable = _node_allocatable(node)

        count = _sum_resources(allocatable, PHYSICAL_GPU_KEYS)

        # 如果节点没有返回物理卡数量，但返回了 vGPU 数量，则按 VGPU_PER_GPU 估算物理卡数量。
        if count <= 0:
            count = _estimated_card_count(
                0,
                _resource_get(allocatable, "nvidia.com/vgpu"),
            )

        if count <= 0:
            continue

        model_map[model] = model_map.get(model, 0) + count

        if model == UNKNOWN_GPU_MODEL:
            unknown_nodes.append(_node_name(node))

    category_items = [
        {"model": model, "count": count}
        for model, count in model_map.items()
    ]
    category_items.sort(key=lambda item: item["count"], reverse=True)

    node_rows = _node_card_rows(context)
    top_nodes_result = _nodes_from_context(context, query, node_rows)
    top_nodes = top_nodes_result.get("items", [])[:5] if top_nodes_result.get("is_success") else []

    return _ok({
        "collected_at": context["collected_at"],
        "metric_source": context["metric_source"],
        "resources": resources,
        "category_items": category_items,
        "top_nodes": top_nodes,
        "unknown_model_nodes": unknown_nodes,
        "model_map_configured": bool(_gpu_model_node_map()),
        "diagnostics": context["diagnostics"],
    })

def cards(query):
    # 显卡卡片视图：根据节点资源推导“每张卡”的展示行。
    # 当前没有真实 GPU UUID，因此 card_id 是 node_name + 序号；真实卡级指标需要后续接 exporter。
    context, err = _resource_context(query)
    if err:
        return err
    node_rows = _node_card_rows(context)
    node_result = _nodes_from_context(context, query, node_rows)
    if not node_result.get("is_success"):
        return node_result

    card_items = []
    node_items = node_result.get("items", []) or []

    for node in node_items:
        node_name = node.get("node_name") or "unknown-node"

        physical_gpu_total = int(node.get("physical_gpu_total") or node.get("gpu_total") or 0)
        physical_gpu_used = int(node.get("physical_gpu_used") or node.get("gpu_used") or 0)

        vgpu_total = int(node.get("vgpu_total") or 0)
        vgpu_used = int(node.get("vgpu_used") or 0)

        gpu_core_total = float(node.get("gpu_core_total") or 0)
        gpu_core_used = float(node.get("gpu_core_used") or 0)

        gpu_mem_total_gib = float(node.get("gpu_mem_total_gib") or 0)
        gpu_mem_used_gib = float(node.get("gpu_mem_used_gib") or 0)

        gpu_mode = node.get("gpu_mode") or "unknown"
        vgpu_per_gpu = node.get("vgpu_per_gpu") or _vgpu_per_gpu()

        has_gpu_like_resource = (
            physical_gpu_total > 0
            or vgpu_total > 0
            or gpu_core_total > 0
            or gpu_mem_total_gib > 0
        )

        if not has_gpu_like_resource:
            continue

        card_count = physical_gpu_total or _estimated_card_count(0, vgpu_total)
        if card_count <= 0:
            card_count = 1

        if gpu_mode == "vgpu":
            data_precision = "vgpu_node_label"
            mapping_rule = f"vGPU node label: 1 GPU ≈ {vgpu_per_gpu} vGPU"
            usage_mode = "vGPU 后台调度"
        elif gpu_mode == "gpu":
            data_precision = "physical_gpu_node_label"
            mapping_rule = "physical GPU node label"
            usage_mode = "物理 GPU 调度"
        else:
            data_precision = "node_resource_snapshot"
            mapping_rule = "node resource snapshot"
            usage_mode = "GPU 资源调度"

        per_vgpu_total = _split_value(vgpu_total, card_count)
        per_vgpu_used = _split_value(vgpu_used, card_count)

        per_core_total = _split_value(gpu_core_total, card_count)
        per_core_used = _split_value(gpu_core_used, card_count)

        per_mem_total = _split_value(gpu_mem_total_gib, card_count)
        per_mem_used = _split_value(gpu_mem_used_gib, card_count)

        for index in range(card_count):
            if gpu_mode == "vgpu":
                physical_card_allocated = 0
            else:
                physical_card_allocated = 1 if index < physical_gpu_used else 0

            card_status = "空闲"
            if node.get("health_level") == "red":
                card_status = "高负载"
            elif (
                physical_card_allocated > 0
                or per_vgpu_used > 0
                or per_core_used > 0
                or per_mem_used > 0
            ):
                card_status = "运行中"

            card_items.append({
                "card_id": f"{node_name}-gpu-{index + 1:02d}",
                "card_status": card_status,
                "usage_mode": usage_mode,
                "node_name": node_name,
                "gpu_model": node.get("gpu_model") or UNKNOWN_GPU_MODEL,
                "gpu_mode": gpu_mode,

                "physical_gpu": {
                    "allocated": physical_card_allocated,
                    "total": 1,
                    "percent": 100 if physical_card_allocated else 0,
                },
                "vgpu": {
                    "allocated": per_vgpu_used,
                    "total": per_vgpu_total,
                    "percent": _percent(per_vgpu_used, per_vgpu_total),
                    "per_gpu": vgpu_per_gpu if gpu_mode == "vgpu" else 0,
                },
                "gpu_core": {
                    "allocated": per_core_used,
                    "total": per_core_total,
                    "percent": _percent(per_core_used, per_core_total),
                    "usage_percent": None,
                    "capacity_estimated": node.get("gpu_core_capacity_estimated", False),
                },
                "gpu_memory": {
                    "allocated_gib": per_mem_used,
                    "total_gib": per_mem_total,
                    "percent": _percent(per_mem_used, per_mem_total),
                    "usage_percent": None,
                    "capacity_estimated": node.get("gpu_mem_capacity_estimated", False),
                },

                "data_precision": data_precision,
                "is_real_physical_card": False,
                "metric_source": node.get("metric_source") or METRIC_SOURCE,
                "mapping_rule": mapping_rule,
                "usage_metric_ready": False,
                "usage_metric_source": "not_configured",

                "capacity_estimated": node.get("capacity_estimated", False),
                "capacity_estimation_source": node.get("capacity_estimation_source"),
            })

    return _ok({
        "items": card_items,
        "total": len(card_items),
        "metric_source": METRIC_SOURCE,
        "mapping_rule": "Cards are inferred from node labels and Kubernetes resource snapshots.",
        "note": "Real GPU UUID and runtime usage require device metrics integration.",
    })

