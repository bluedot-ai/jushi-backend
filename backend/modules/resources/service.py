"""Public resources-module use cases.

Keep this module as the stable import facade used by Flask routes, the snapshot
script, application startup, and the deploy precheck. Implementation details
live in focused modules so callers do not need to change during the refactor.
"""

from .collector import quotas
from .accelerator_collector import start_accelerator_metric_collector
from .node_gpu import (
    node_gpu_details as _node_gpu_details,
    node_gpu_trend as _node_gpu_trend,
    validate_node_name,
)
from .recommendation import recommendation
from .response import _error
from .snapshot import start_resource_snapshot_collector
from .trend import _build_trend_response, trend
from .trend_cache import start_resource_trend_cache_refresher as _start_trend_cache_refresher
from .views import cards, gpus, nodes, summary


def _available_node(node_name, query):
    node_name, validation_error = validate_node_name(node_name)
    if validation_error:
        return None, _error(validation_error, 400)

    node_query = dict(query or {})
    node_query["node_name"] = node_name
    payload = nodes(node_query)
    if payload.get("is_success") is False:
        return None, payload

    items = payload.get("items") or []
    if not items:
        return None, _error("Node not found", 404)

    source = items[0]
    if source.get("status") != "Ready" or source.get("schedulable") is False:
        return None, _error("Node is not Ready and schedulable", 409)
    node = {
        key: source.get(key)
        for key in (
            "node_name",
            "status",
            "schedulable",
            "health_level",
            "health_text",
            "gpu_vendor",
            "gpu_model",
            "physical_gpu_total",
            "physical_gpu_used",
            "physical_gpu_available",
            "physical_gpu_alloc_percent",
            "gpu_mem_total_gib",
            "gpu_mem_used_gib",
            "gpu_mem_usage_percent",
            "collected_at",
        )
    }
    return node, None


def node_gpus(node_name, query):
    node, error = _available_node(node_name, query)
    if error:
        return error
    return _node_gpu_details(node_name, node)


def node_gpu_trend(node_name, query):
    node, error = _available_node(node_name, query)
    if error:
        return error
    return _node_gpu_trend(
        node_name,
        str((query or {}).get("metric") or "memory_utilization"),
        str((query or {}).get("range") or "1h"),
        node,
    )


def start_resource_trend_cache_refresher():
    return _start_trend_cache_refresher(_build_trend_response)


__all__ = [
    "start_resource_snapshot_collector",
    "start_resource_trend_cache_refresher",
    "start_accelerator_metric_collector",
    "summary",
    "nodes",
    "node_gpus",
    "node_gpu_trend",
    "gpus",
    "quotas",
    "cards",
    "trend",
    "recommendation",
]

