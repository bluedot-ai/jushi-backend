"""Per-device identities and models; never expand a node model into card models."""

from collections import defaultdict

try:
    from backend.config import Config
    from backend.services.prometheus_client import PrometheusClient
except ModuleNotFoundError:
    from config import Config
    from services.prometheus_client import PrometheusClient

from .constants import UNKNOWN_GPU_MODEL
from .settings import _prometheus_gpu_usage_enabled


INVENTORY_QUERIES = {
    "nvidia": 'max by (node, Hostname, hostname, kubernetes_node, UUID, gpu, device, modelName, GPU_I_ID) '
              '(DCGM_FI_DEV_FB_TOTAL{job="nvidia-dcgm-exporter"})',
    "ascend": 'max by (node, Hostname, hostname, kubernetes_node, id, vdie_id, model_name, pcie_bus_info, is_virtual, v_dev_id) '
              '(npu_chip_info_total_memory{job="npu-exporter"})',
}


def _metadata(metric, vendor):
    node = next((str(metric.get(key) or "").strip() for key in (
        "node", "Hostname", "hostname", "kubernetes_node"
    ) if metric.get(key)), "")
    if vendor == "nvidia":
        card_id = str(metric.get("UUID") or "").strip()
        if not card_id.upper().startswith("GPU-") or metric.get("GPU_I_ID") not in (None, "", "-1"):
            return None
        raw_index, device, model = metric.get("gpu"), metric.get("device"), metric.get("modelName")
    else:
        if str(metric.get("is_virtual", "false")).lower() in ("true", "1") or metric.get("v_dev_id") not in (None, "", "-1"):
            return None
        card_id = str(metric.get("vdie_id") or metric.get("pcie_bus_info") or "").strip()
        raw_index, device, model = metric.get("id"), metric.get("pcie_bus_info"), metric.get("model_name")
    if not node or not card_id:
        return None
    raw_index = str(raw_index if raw_index is not None else "").strip()
    index = int(raw_index) if raw_index.isdigit() else None
    return {"node_name": node, "vendor": vendor, "card_id": card_id,
            "device_index": index, "device_name": str(device or "").strip(),
            "gpu_model": str(model or "").strip() or UNKNOWN_GPU_MODEL,
            "is_real_physical_card": True, "model_source": "prometheus_device_labels"}


def card_inventory(node_items):
    """One bounded pair of queries for all nodes, with explicit unidentified slots."""
    expected = {item["node_name"]: int(item.get("physical_gpu_total") or item.get("gpu_total") or 0)
                for item in node_items if item.get("node_name")}
    diagnostics = {"failed_queries": [], "skipped_identity_rows": 0, "metadata_conflicts": 0,
                   "inventory_count_mismatch_nodes": []}
    devices = {}
    if expected and _prometheus_gpu_usage_enabled():
        client = PrometheusClient.from_config(Config)
        for vendor, query in INVENTORY_QUERIES.items():
            try:
                rows, error = client.query(query)
            except Exception:
                rows, error = [], True
            if error:
                diagnostics["failed_queries"].append(vendor)
                continue
            for row in rows or []:
                item = _metadata(row.get("metric") or {}, vendor)
                if not item:
                    diagnostics["skipped_identity_rows"] += 1
                    continue
                if item["node_name"] not in expected:
                    continue
                key = (item["node_name"], vendor, item["card_id"])
                if key not in devices:
                    devices[key] = item
                    continue
                previous = devices[key]
                for field, missing in (("gpu_model", UNKNOWN_GPU_MODEL), ("device_index", None), ("device_name", "")):
                    if previous[field] != item[field]:
                        previous[field] = missing
                        diagnostics["metadata_conflicts"] += 1

    by_node = defaultdict(list)
    for item in devices.values():
        by_node[item["node_name"]].append(item)
    items = []
    for node, count in expected.items():
        observed = sorted(by_node[node], key=lambda item: (
            item["vendor"], item["device_index"] if item["device_index"] is not None else 10**9, item["card_id"]
        ))
        if len(observed) != count:
            diagnostics["inventory_count_mismatch_nodes"].append(node)
        items.extend(observed)
        # A missing exporter is not evidence that a card disappeared. Preserve
        # the resource count, but do not invent its UUID, index, or model.
        for slot in range(max(count - len(observed), 0)):
            items.append({"node_name": node, "vendor": None,
                          "card_id": f"{node}-unidentified-{slot + 1:02d}",
                          "device_index": None, "device_name": "", "gpu_model": UNKNOWN_GPU_MODEL,
                          "is_real_physical_card": False, "model_source": "unidentified"})
    return items, diagnostics
