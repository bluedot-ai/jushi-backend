"""Mixed NVIDIA/Ascend and pure Ascend contracts; no live devices required."""
import os
import unittest
from copy import deepcopy
from datetime import datetime
from unittest.mock import Mock, patch

from backend.modules.resources import gpu_allocation_collector as collector
from backend.tests.test_gpu_allocation_collector import BusinessFragmentPrometheus, FakeK8s, FakePrometheus, node, pod


def ascend_node(name="npu", count=2, resource="huawei.com/Ascend310P", **kwargs):
    result = node(name, count, **kwargs)
    for field in ("capacity", "allocatable"):
        result["status"][field] = {resource: str(count)}
    return result


def ascend_pod(name="npu-work", count=1):
    result = pod(name, "npu", count=count)
    result["spec"]["containers"][0]["resources"]["requests"] = {"huawei.com/Ascend310P": str(count)}
    return result


class MixedPrometheus(FakePrometheus):
    def __init__(self):
        super().__init__()
        self.ascend_error = None
        self.ascend_missing = None
        self.transform = lambda rows: rows

    def query(self, query):
        if "npu_chip_info_" not in query:
            return super().query(query)
        if self.ascend_error:
            return [], self.ascend_error
        name = "utilization" if "_utilization" in query else "used" if "_used_memory" in query else "total"
        end = int(query.rsplit("@", 1)[1].strip())
        rows = []
        values = {"utilization": [40, 60], "used": [100, 50], "total": [200, 300]}
        for index, value in enumerate(values[name]):
            if self.ascend_missing == name and index == 1:
                continue
            rows.append({"metric": {"node": "npu", "id": str(index),
                         "pcie_bus_info": f"0000:0{index+1}:00.0", "vdie_id": f"npu-uuid-{index}",
                         "model_name": "310P3-Ascend-V1"},
                         "values": [[end - (9-offset)*30, str(value)] for offset in range(10)]})
        return self.transform(rows), None


class AscendAllocationTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            "GPU_ALLOCATION_HISTORY_ENABLED": "true", "GPU_ALLOCATION_INTERVAL_SECONDS": "300",
            "GPU_ALLOCATION_CLUSTER_NAME": "test", "PROMETHEUS_GPU_USAGE_ENABLED": "true",
            "GPU_ALLOCATION_PHYSICAL_RESOURCE_KEY": "nvidia.com/gpu",
            "GPU_ALLOCATION_ASCEND_PHYSICAL_RESOURCE_KEYS": "huawei.com/Ascend310P",
            "GPU_ALLOCATION_MONITOR_SCRAPE_INTERVAL_SECONDS": "30",
            "GPU_ALLOCATION_NVIDIA_MONITOR_SCRAPE_INTERVAL_SECONDS": "30",
            "GPU_ALLOCATION_ASCEND_MONITOR_SCRAPE_INTERVAL_SECONDS": "30",
            "GPU_ALLOCATION_NVIDIA_MEMORY_UNIT": "MiB", "GPU_ALLOCATION_ASCEND_MEMORY_UNIT": "MB",
            "GPU_ALLOCATION_MONITOR_COVERAGE_FRACTION": "0.8",
        })
        env.start()
        self.addCleanup(env.stop)

    def build(self, vendor="all", k8s=None, prom=None):
        k8s = k8s or FakeK8s([node(), ascend_node()], [pod(), ascend_pod()])
        with patch.object(collector.K8sClient, "from_config", return_value=k8s), \
             patch.object(collector.PrometheusClient, "from_config", return_value=prom or MixedPrometheus()):
            return collector.build_current_snapshot(datetime(2026, 10, 10, 16, 0), vendor)

    def test_mixed_allocation_and_cross_vendor_byte_weighting(self):
        result, diagnostics = self.build()
        self.assertEqual(result["vendor"], "all")
        self.assertEqual((result["gpu_capacity"], result["gpu_allocatable"], result["gpu_allocated"]), (4, 4, 2))
        self.assertEqual(result["allocation_rate"], 50)
        self.assertEqual(result["gpu_utilization_avg"], 35)
        expected = (100*1024**2 + 150*1000**2) / (400*1024**2 + 500*1000**2) * 100
        self.assertAlmostEqual(result["gpu_memory_utilization"], expected, places=4)
        self.assertTrue(result["monitor_valid"])
        self.assertEqual(result["calculation_version"], "physical-accelerator-v2")
        self.assertEqual(len(result["vendors"]), 2)
        self.assertNotIn("_memory_used_bytes", result["vendors"][1])
        self.assertEqual(diagnostics["allocation_issues"], [])

    def test_pure_ascend_has_valid_all_metrics_without_nvidia(self):
        result, _ = self.build(k8s=FakeK8s([ascend_node()], [ascend_pod()]))
        self.assertEqual(result["gpu_capacity"], 2)
        self.assertEqual(result["gpu_utilization_avg"], 50)
        self.assertEqual(result["gpu_memory_utilization"], 30)
        self.assertTrue(result["monitor_valid"])
        self.assertEqual(result["vendors"][0]["gpu_capacity"], 0)

    def test_selecting_ascend_only_does_not_include_nvidia(self):
        result, _ = self.build("ascend")
        self.assertEqual(result["vendor"], "ascend")
        self.assertEqual(result["gpu_capacity"], 2)
        self.assertEqual(result["gpu_utilization_avg"], 50)
        self.assertEqual(result["gpu_memory_utilization"], 30)

    def test_missing_ascend_monitor_does_not_publish_nvidia_as_all(self):
        prom = MixedPrometheus()
        prom.ascend_error = "missing"
        result, _ = self.build(prom=prom)
        self.assertTrue(result["allocation_valid"])
        self.assertIsNone(result["gpu_utilization_avg"])
        self.assertIsNone(result["gpu_memory_utilization"])
        self.assertEqual(result["vendors"][0]["gpu_utilization_avg"], 20)

    def test_independent_monitor_coverage_ascend_memory_survives_missing_util(self):
        prom = MixedPrometheus()
        prom.ascend_missing = "utilization"
        result, _ = self.build(prom=prom)
        self.assertIsNone(result["gpu_utilization_avg"])
        self.assertIsNotNone(result["gpu_memory_utilization"])

    def test_node_and_cluster_pod_lists_fetched_once_per_snapshot(self):
        k8s = FakeK8s([node(), ascend_node()], [pod(), ascend_pod()])
        k8s.list_nodes = Mock(wraps=k8s.list_nodes)
        k8s.list_cluster_pods = Mock(wraps=k8s.list_cluster_pods)
        self.build(k8s=k8s)
        k8s.list_nodes.assert_called_once_with()
        k8s.list_cluster_pods.assert_called_once_with()

    def test_three_vendor_scopes_saved_without_nested_data(self):
        snapshot, diagnostics = self.build()
        with patch.object(collector, "build_current_snapshot", return_value=(snapshot, diagnostics)), \
             patch.object(collector, "save_snapshot", return_value=None) as save:
            result = collector.collect_and_save_once()
        self.assertTrue(result["saved"])
        self.assertEqual(result["saved_vendors"], ["all", "nvidia", "ascend"])
        self.assertEqual(save.call_count, 3)
        self.assertTrue(all("vendors" not in call.args[0] for call in save.call_args_list))

    def test_one_vendor_write_error_does_not_stop_other_scopes(self):
        snapshot, diagnostics = self.build()
        with patch.object(collector, "build_current_snapshot", return_value=(snapshot, diagnostics)), \
             patch.object(collector, "save_snapshot", side_effect=[None, RuntimeError("db"), None]) as save:
            result = collector.collect_and_save_once()
        self.assertEqual(save.call_count, 3)
        self.assertFalse(result["saved"])
        self.assertEqual(result["saved_vendors"], ["all", "ascend"])

    def test_notready_ascend_counts_in_capacity_not_schedulable_or_allocated(self):
        result, _ = self.build("ascend", k8s=FakeK8s([ascend_node(ready=False)], [ascend_pod()]))
        self.assertEqual((result["gpu_capacity"], result["gpu_allocatable"], result["gpu_allocated"]), (2, 0, 0))
        self.assertIsNone(result["allocation_rate"])

    def test_unknown_ascend_resource_not_silently_zero_in_all(self):
        result, diagnostics = self.build(k8s=FakeK8s([node(), ascend_node(resource="huawei.com/Ascend910B")], [pod()]))
        self.assertFalse(result["allocation_valid"])
        self.assertIsNone(result["gpu_capacity"])
        self.assertIn("ascend:ascend_resource_key_not_configured", diagnostics["allocation_issues"])

    def test_configured_whole_ascend910_resource_is_supported(self):
        workload = ascend_pod()
        workload["spec"]["containers"][0]["resources"]["requests"] = {"huawei.com/Ascend910B": "1"}
        with patch.dict(os.environ, {"GPU_ALLOCATION_ASCEND_PHYSICAL_RESOURCE_KEYS": "huawei.com/Ascend310P,huawei.com/Ascend910B"}):
            result, _ = self.build("ascend", k8s=FakeK8s([ascend_node(resource="huawei.com/Ascend910B")], [workload]))
        self.assertEqual(result["gpu_allocated"], 1)
        self.assertTrue(result["monitor_valid"])

    def test_virtual_partition_labels_rejected_not_counted_as_cards(self):
        prom = MixedPrometheus()
        prom.transform = lambda rows: [{**row, "metric": {**row["metric"], "is_virtual": "true"}} for row in rows]
        result, _ = self.build("ascend", prom=prom)
        self.assertIsNone(result["gpu_utilization_avg"])
        self.assertFalse(result["monitor_valid"])

    def test_vdie_uuid_without_physical_id_or_pci_not_accepted(self):
        prom = MixedPrometheus()
        def remove_physical(rows):
            for row in rows:
                row["metric"].pop("id")
                row["metric"].pop("pcie_bus_info")
            return rows
        prom.transform = remove_physical
        result, _ = self.build("ascend", prom=prom)
        self.assertFalse(result["monitor_valid"])

    def test_two_different_vdie_uuid_for_same_physical_device_rejected(self):
        prom = MixedPrometheus()
        def duplicate(rows):
            extra = deepcopy(rows[0])
            extra["metric"]["vdie_id"] = "other-partition"
            return rows + [extra]
        prom.transform = duplicate
        result, _ = self.build("ascend", prom=prom)
        self.assertFalse(result["monitor_valid"])

    def test_ascend_job_selector_override_keeps_raw_five_minute_window(self):
        with patch.dict(os.environ, {"GPU_ALLOCATION_ASCEND_UTILIZATION_PROMQL": 'npu_chip_info_utilization{job="site-npu"}'}):
            queries = collector.providers._monitor_queries(1000, "ascend")
        self.assertEqual(queries["utilization"], 'npu_chip_info_utilization{job="site-npu"}[5m] @ 1000')

    def test_preaggregated_selector_cannot_bypass_device_coverage(self):
        with patch.dict(os.environ, {"GPU_ALLOCATION_ASCEND_UTILIZATION_PROMQL": "avg(npu_chip_info_utilization)"}):
            result, diagnostics = self.build("ascend")
        self.assertTrue(result["allocation_valid"])
        self.assertFalse(result["monitor_valid"])
        self.assertIn("monitor_collection_failed", diagnostics["monitor_issues"])

    def test_per_vendor_scrape_interval_does_not_change_other_vendor(self):
        with patch.dict(os.environ, {"GPU_ALLOCATION_ASCEND_MONITOR_SCRAPE_INTERVAL_SECONDS": "15"}):
            result, _ = self.build()
        self.assertFalse(result["monitor_valid"])
        self.assertIsNone(result["gpu_utilization_avg"])
        self.assertTrue(result["vendors"][0]["monitor_valid"])

    def test_ascend_memory_unit_can_match_site_exporter(self):
        with patch.dict(os.environ, {"GPU_ALLOCATION_ASCEND_MEMORY_UNIT": "MiB"}):
            result, _ = self.build()
        self.assertAlmostEqual(result["gpu_memory_utilization"], 250/900*100, places=4)

    def test_virtual_resource_blocks_physical_ascend_allocation(self):
        npu = ascend_node()
        npu["status"]["capacity"]["huawei.com/Ascend310P-2c"] = "8"
        result, _ = self.build("ascend", k8s=FakeK8s([npu], [ascend_pod()]))
        self.assertFalse(result["allocation_valid"])

    def test_zero_partition_aliases_do_not_block_whole_ascend_cards(self):
        npu = ascend_node()
        for field in ("capacity", "allocatable"):
            for suffix in ("1c", "2c", "4c", "4c.3cpu"):
                npu["status"][field]["huawei.com/Ascend310P-" + suffix] = "0"
        result, diagnostics = self.build("ascend", k8s=FakeK8s([npu], [ascend_pod()]))
        self.assertTrue(result["allocation_valid"])
        self.assertTrue(result["monitor_valid"])
        self.assertEqual(result["gpu_capacity"], 2)
        self.assertEqual(diagnostics["allocation_issues"], [])

    def test_positive_or_malformed_partition_quantity_in_either_map_is_rejected(self):
        for field in ("capacity", "allocatable"):
            for quantity in ("1", "-1", "NaN", "0.5", None, "invalid"):
                with self.subTest(field=field, quantity=quantity):
                    npu = ascend_node()
                    for resource_map in ("capacity", "allocatable"):
                        npu["status"][resource_map]["huawei.com/Ascend310P-2c"] = "0"
                    npu["status"][field]["huawei.com/Ascend310P-2c"] = quantity
                    result, _ = self.build("ascend", k8s=FakeK8s([npu], [ascend_pod()]))
                    self.assertFalse(result["allocation_valid"])

    def test_zero_partition_alias_does_not_bypass_enabled_sharing_label(self):
        npu = ascend_node(labels={"huawei.com/vnpu": "true"})
        npu["status"]["capacity"]["huawei.com/Ascend310P-2c"] = "0"
        result, _ = self.build("ascend", k8s=FakeK8s([npu], [ascend_pod()]))
        self.assertFalse(result["allocation_valid"])

    def test_mixed_fragmented_cards_zero_aliases_and_offline_node(self):
        class SitePrometheus(MixedPrometheus, BusinessFragmentPrometheus):
            pass
        prom = SitePrometheus()
        prom.cards = [("mixed-worker", f"GPU-{index}", 0, 0, 0, 24576) for index in range(6)]
        prom.cards.append(("new-worker", "GPU-new", 0, 0, 0, 24576))
        npu = ascend_node()
        for field in ("capacity", "allocatable"):
            npu["status"][field]["huawei.com/Ascend310P-2c"] = "0"
        nodes = [node("mixed-worker", 6, labels={"nvidia.com/gpu.count": "4"}),
                 node("new-worker", 1), npu, ascend_node("offline-npu", 4, ready=False, unschedulable=True)]
        workload = pod("inference", "mixed-worker", count=5)
        with patch.dict(os.environ, {"GPU_ALLOCATION_NVIDIA_MONITOR_SCRAPE_INTERVAL_SECONDS": "15"}):
            result, diagnostics = self.build(k8s=FakeK8s(nodes, [workload, ascend_pod()]), prom=prom)
        self.assertTrue(result["allocation_valid"])
        self.assertEqual((result["gpu_capacity"], result["gpu_allocatable"], result["gpu_allocated"]), (13, 9, 6))
        self.assertTrue(result["vendors"][0]["monitor_valid"])
        self.assertFalse(result["vendors"][1]["monitor_valid"])
        self.assertIsNone(result["gpu_utilization_avg"])
        self.assertEqual(diagnostics["allocation_issues"], [])


if __name__ == "__main__":
    unittest.main()
