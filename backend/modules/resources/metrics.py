"""Resource-specific PromQL and GPU/NPU metric mapping."""

try:
    from backend.config import Config
    from backend.services.prometheus_client import PrometheusClient
except ModuleNotFoundError:
    from config import Config
    from services.prometheus_client import PrometheusClient

from .constants import PROMETHEUS_METRIC_SOURCE
from .parser import _mib_to_gib, _percent, _safe_get
from .settings import _prometheus_gpu_usage_enabled


def _prometheus_query(promql):
    if not _prometheus_gpu_usage_enabled():
        return None, "disabled"
    return PrometheusClient.from_config(Config).query(promql)


def _prometheus_vector_by_node(promql):
    rows, error = _prometheus_query(promql)
    if error:
        return {}, error

    values = {}
    for row in rows:
        metric = row.get("metric") or {}
        node = str(metric.get("node") or metric.get("Hostname") or "").strip()
        value = row.get("value") or []
        if not node or len(value) < 2:
            continue
        try:
            values[node] = values.get(node, 0.0) + float(value[1])
        except (TypeError, ValueError):
            continue
    return values, None


def _prometheus_gpu_memory_by_node():
    if not _prometheus_gpu_usage_enabled():
        return {}, None

    queries = {
        "nvidia_used_mib": 'sum by (node) (DCGM_FI_DEV_FB_USED{job="nvidia-dcgm-exporter"})',
        "nvidia_total_mib": 'sum by (node) (DCGM_FI_DEV_FB_TOTAL{job="nvidia-dcgm-exporter"})',
        "ascend_used_mib": 'sum by (node) (npu_chip_info_used_memory{job="npu-exporter"})',
        "ascend_total_mib": 'sum by (node) (npu_chip_info_total_memory{job="npu-exporter"})',
    }

    query_results = {}
    errors = []
    for key, promql in queries.items():
        values, error = _prometheus_vector_by_node(promql)
        query_results[key] = values
        if error:
            errors.append(f"{key}: {error}")

    nodes = set()
    for values in query_results.values():
        nodes.update(values.keys())

    result = {}
    for node in nodes:
        used_mib = (
            query_results["nvidia_used_mib"].get(node, 0.0)
            + query_results["ascend_used_mib"].get(node, 0.0)
        )
        total_mib = (
            query_results["nvidia_total_mib"].get(node, 0.0)
            + query_results["ascend_total_mib"].get(node, 0.0)
        )
        if total_mib <= 0:
            continue
        result[node] = {
            "gpu_mem_used_gib": _mib_to_gib(used_mib),
            "gpu_mem_total_gib": _mib_to_gib(total_mib),
        }

    return result, "; ".join(errors) if errors else None


def _apply_prometheus_memory_to_cards(cards, memory_usage):
    if not memory_usage:
        return cards

    used_gib = float(memory_usage.get("gpu_mem_used_gib") or 0)
    prometheus_total_gib = float(memory_usage.get("gpu_mem_total_gib") or 0)
    total_gib = round(prometheus_total_gib, 2)
    if total_gib <= 0:
        return cards

    used_gib = round(min(max(used_gib, 0), total_gib), 2)
    percent = _percent(used_gib, total_gib)
    cards.update({
        "gpu_mem_total_gib": total_gib,
        "gpu_mem_used_gib": used_gib,
        "gpu_mem_alloc_percent": percent,
        "gpu_mem_percent": percent,
        "gpu_mem_usage_percent": percent,
        "gpu_mem_capacity_estimated": False,
        "usage_metric_ready": True,
        "usage_metric_source": PROMETHEUS_METRIC_SOURCE,
    })
    return cards

