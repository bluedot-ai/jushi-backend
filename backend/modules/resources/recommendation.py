"""Resource recommendation rules."""

from .constants import METRIC_SOURCE
from .aggregator import _node_card_rows
from .collector import _resource_context
from .response import _ok
from .views import _nodes_from_context, _summary_from_context


def _node_score(item):
    return max(
        item.get("vgpu_alloc_percent", 0),
        item.get("gpu_alloc_percent", 0),
        item.get("gpu_mem_alloc_percent", 0),
        item.get("gpu_core_alloc_percent", 0),
    )


def recommendation(query):
    # 推荐策略：根据整体资源分配率和节点排序，给出推荐节点、避让节点和风险提示。
    # 这里只是轻量启发式规则，不会真正影响 Kubernetes 调度。
    context, err = _resource_context(query)
    if err:
        return err

    node_rows = _node_card_rows(context)
    summary_result = _summary_from_context(context, node_rows)
    if not summary_result.get("is_success"):
        return summary_result

    node_result = _nodes_from_context(context, query, node_rows)
    node_items = node_result.get("items", []) if node_result.get("is_success") else []

    cards_data = summary_result.get("cards", {})
    max_percent = max(
        cards_data.get("gpu_alloc_percent", 0),
        cards_data.get("vgpu_alloc_percent", 0),
        cards_data.get("gpu_mem_alloc_percent", 0),
        cards_data.get("gpu_core_alloc_percent", 0),
    )

    recommended_node = None
    avoid_nodes = []
    reason = []

    if node_items:
        sorted_nodes = sorted(node_items, key=_node_score)
        recommended_node = sorted_nodes[0].get("node_name")
        reason.append(f"{recommended_node} 当前资源分配率相对较低")

        avoid_nodes = [
            item.get("node_name")
            for item in sorted_nodes
            if _node_score(item) >= 80
        ]

        if avoid_nodes:
            reason.append("部分节点已进入中高负载区间，建议暂缓新增普通任务")

    if max_percent >= 90:
        priority = "高"
        mode = "高优先级排队"
        risk = "高，建议暂停低优先级创建"
        suggestion = "资源接近满载，建议优先保障生产任务，暂停非必要实例创建。"
    elif max_percent >= 70:
        priority = "中"
        mode = "优先调度低负载节点"
        risk = "中，需观察峰值"
        suggestion = "资源进入中高负载区间，建议优先选择空闲节点并控制弹性任务数量。"
    else:
        priority = "低"
        mode = "自动推荐"
        risk = "低，可继续创建实例"
        suggestion = "当前资源余量较充足，可以继续创建实例或开启弹性任务。"

    if recommended_node:
        suggestion = f"建议优先调度到 {recommended_node}。" + suggestion

    return _ok({
        "recommend_mode": mode,
        "recommended_node": recommended_node,
        "avoid_nodes": avoid_nodes,
        "expected_occupation": {
            "gpu_available": cards_data.get("gpu_available", 0),
            "vgpu_available": cards_data.get("vgpu_available", 0),
            "gpu_memory_available_gib": round(
                cards_data.get("gpu_mem_total_gib", 0) - cards_data.get("gpu_mem_used_gib", 0),
                2,
            ),
        },
        "strategy": "60% 主任务 + 30% 弹性 + 10% 预留",
        "risk_level": risk,
        "priority": priority,
        "reason": reason,
        "suggestion": suggestion,
        "metric_source": METRIC_SOURCE,
        "usage_metric_ready": False,
    })

