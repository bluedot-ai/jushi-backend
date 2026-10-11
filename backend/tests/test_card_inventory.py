import unittest
from unittest.mock import patch

from backend.modules.resources import card_inventory as inventory, views


MODELS = ["RTX 4090", "RTX 3090", "RTX 3090", "RTX 4090", "RTX 3090", "RTX 3090"]


def nvidia_rows():
    return [{"metric": {"node": "worker-mixed", "UUID": f"GPU-{index}",
                        "gpu": str(index), "device": f"nvidia{index}", "modelName": model},
             "value": [100, "24576"]} for index, model in enumerate(MODELS)]


class FakeClient:
    def __init__(self, rows=None, fail=False):
        self.rows = nvidia_rows() if rows is None else rows
        self.fail = fail
        self.calls = []

    def query(self, query):
        self.calls.append(query)
        if self.fail:
            return [], "private details must not leak"
        return (self.rows if "DCGM" in query else []), None


class CardInventoryTests(unittest.TestCase):
    def collect(self, client, nodes=None):
        nodes = nodes or [{"node_name": "worker-mixed", "physical_gpu_total": 6, "gpu_model": "RTX 3090"}]
        with patch.object(inventory, "_prometheus_gpu_usage_enabled", return_value=True), patch.object(
            inventory.PrometheusClient, "from_config", return_value=client
        ):
            return inventory.card_inventory(nodes)

    def test_mixed_models_follow_uuid_and_original_index_not_row_order(self):
        client = FakeClient(list(reversed(nvidia_rows())))
        items, diagnostics = self.collect(client)
        self.assertEqual([row["gpu_model"] for row in items], MODELS)
        self.assertEqual([row["device_index"] for row in items], list(range(6)))
        self.assertEqual([row["card_id"] for row in items], [f"GPU-{i}" for i in range(6)])
        self.assertEqual(diagnostics["inventory_count_mismatch_nodes"], [])
        self.assertEqual(len(client.calls), 2)

    def test_partial_monitoring_never_fills_missing_models_from_node_label(self):
        items, diagnostics = self.collect(FakeClient(nvidia_rows()[:2]))
        self.assertEqual(len(items), 6)
        self.assertEqual([row["gpu_model"] for row in items[:2]], MODELS[:2])
        for row in items[2:]:
            self.assertEqual(row["gpu_model"], "Unknown")
            self.assertIsNone(row["device_index"])
            self.assertFalse(row["is_real_physical_card"])
        self.assertEqual(diagnostics["inventory_count_mismatch_nodes"], ["worker-mixed"])

    def test_query_failure_preserves_count_without_exposing_error_details(self):
        items, diagnostics = self.collect(FakeClient(fail=True))
        self.assertEqual(len(items), 6)
        self.assertTrue(all(row["gpu_model"] == "Unknown" for row in items))
        self.assertEqual(diagnostics["failed_queries"], ["nvidia", "ascend"])
        self.assertNotIn("private", str(diagnostics))

    def test_duplicate_series_not_counted_twice_and_model_conflict_unknown(self):
        rows = nvidia_rows()
        duplicate = {**rows[0], "metric": {**rows[0]["metric"], "modelName": "conflicting"}}
        items, diagnostics = self.collect(FakeClient(rows + [rows[1], duplicate]))
        self.assertEqual(len(items), 6)
        self.assertEqual(items[0]["gpu_model"], "Unknown")
        self.assertEqual(diagnostics["metadata_conflicts"], 1)

    def test_unknown_nodes_missing_uuid_and_mig_not_misassigned(self):
        row = nvidia_rows()[0]
        rows = [
            {**row, "metric": {**row["metric"], "node": "other-cluster"}},
            {**row, "metric": {**row["metric"], "UUID": ""}},
            {**row, "metric": {**row["metric"], "GPU_I_ID": "0"}},
        ]
        items, diagnostics = self.collect(FakeClient(rows))
        self.assertTrue(all(not row["is_real_physical_card"] for row in items))
        self.assertEqual(diagnostics["skipped_identity_rows"], 2)

    def test_ascend_uuid_pci_and_index_are_used(self):
        class AscendClient:
            def query(self, query):
                return ([] if "DCGM" in query else [{"metric": {
                    "Hostname": "worker-ascend", "vdie_id": "NPU-a", "id": "0",
                    "pcie_bus_info": "0000:01:00.0", "model_name": "Ascend 310P"
                }, "value": [100, "21000"]}]), None
        items, _ = self.collect(AscendClient(), [{"node_name": "worker-ascend", "physical_gpu_total": 2}])
        self.assertEqual(items[0]["card_id"], "NPU-a")
        self.assertEqual(items[0]["device_index"], 0)
        self.assertEqual(items[0]["device_name"], "0000:01:00.0")
        self.assertEqual(items[0]["gpu_model"], "Ascend 310P")
        self.assertEqual(items[1]["gpu_model"], "Unknown")

    def test_category_and_card_contracts_use_same_per_device_metadata(self):
        node = {"node_name": "worker-mixed", "physical_gpu_total": 6,
                "physical_gpu_used": 5, "gpu_mode": "gpu", "gpu_model": "RTX 3090",
                "gpu_mem_total_gib": 144, "gpu_mem_used_gib": 3,
                "gpu_mem_capacity_estimated": True}
        context = {"raw_nodes": [], "allocatable": {}, "allocated": {}, "collected_at": "now",
                   "metric_source": "test", "diagnostics": {}}
        with patch.object(views, "_resource_context", return_value=(context, None)), patch.object(
            views, "_node_card_rows", return_value=[]
        ), patch.object(views, "_nodes_from_context", return_value={"is_success": True, "items": [node]}), patch.object(
            inventory, "_prometheus_gpu_usage_enabled", return_value=True
        ), patch.object(inventory.PrometheusClient, "from_config", return_value=FakeClient()):
            categories = views.gpus({})
            cards = views.cards({})
        self.assertEqual(categories["category_items"], [{"model": "RTX 3090", "count": 4}, {"model": "RTX 4090", "count": 2}])
        self.assertEqual([row["gpu_model"] for row in cards["items"]], MODELS)
        self.assertTrue(all(row["is_real_physical_card"] for row in cards["items"]))
        self.assertTrue(all(row["physical_gpu"]["allocated"] is None for row in cards["items"]))
        self.assertTrue(all(row["gpu_memory"]["allocated_gib"] is None for row in cards["items"]))


if __name__ == "__main__":
    unittest.main()
