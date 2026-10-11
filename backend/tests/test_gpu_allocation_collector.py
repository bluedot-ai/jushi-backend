import os
from copy import deepcopy
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from backend.modules.resources import gpu_allocation_collector as collector


def node(name="worker", count=2, *, ready=True, unschedulable=False, labels=None):
    return {"metadata": {"name": name, "labels": labels or {}},
            "spec": {"unschedulable": unschedulable},
            "status": {"capacity": {"nvidia.com/gpu": str(count)},
                       "allocatable": {"nvidia.com/gpu": str(count)},
                       "conditions": [{"type": "Ready", "status": "True" if ready else "False"}]}}


def container(count, *, request=True, restartable=False):
    item = {"resources": {"requests" if request else "limits": {"nvidia.com/gpu": str(count)}}}
    if restartable:
        item["restartPolicy"] = "Always"
    return item


def pod(name="p", node_name="worker", phase="Running", count=1):
    return {"metadata": {"name": name, "namespace": "business"},
            "spec": {"nodeName": node_name, "containers": [container(count)]},
            "status": {"phase": phase}}


class FakeK8s:
    api_base = "https://kubernetes.invalid"
    token = "fake-test-token"

    def __init__(self, nodes=None, pods=None):
        self.nodes = nodes if nodes is not None else [node()]
        self.pods = pods if pods is not None else [pod()]
        self.continuation = ""

    def list_nodes(self):
        return 200, {"items": self.nodes, "metadata": {}}

    def list_cluster_pods(self):
        return 200, {"items": self.pods, "metadata": {"continue": self.continuation}}


class FakePrometheus:
    def __init__(self):
        self.cards = [("worker", "GPU-a", 10, 20, 25, 100),
                      ("worker", "GPU-b", 30, 60, 75, 300)]
        self.missing = None
        self.duplicate = False

    def query(self, query):
        if "GPU_UTIL" in query:
            field = 2
        elif "FB_USED" in query:
            field = 4
        else:
            field = 5
        cards = self.cards[:-1] if self.missing == field else self.cards
        end = int(query.rsplit("@", 1)[1].strip())
        rows = []
        for item in cards:
            if field == 2:
                values = [(item[2] * 10 - item[3]) / 9] * 9 + [item[3]]
            else:
                values = [item[field]] * 10
            rows.append({"metric": {"Hostname": item[0], "UUID": item[1]},
                         "values": [[end - (9 - index) * 30, str(value)] for index, value in enumerate(values)]})
        if self.duplicate and rows:
            rows.append(rows[0])
        return rows, None


class BusinessFragmentPrometheus(FakePrometheus):
    """One physical exporter, seven ownership segments, real 15s scrapes."""
    def query(self, query):
        rows, error = super().query(query)
        end = int(query.rsplit("@", 1)[1].strip())
        result = []
        for row in rows:
            points = [[end - (19 - index) * 15, row["values"][index // 2][1]] for index in range(20)]
            offset = 0
            for index, length in enumerate((2, 2, 3, 3, 3, 3, 4)):
                metric = {**row["metric"], "instance": "exporter.invalid:9400",
                          "job": "dcgm", "pod": "exporter-pod"}
                if index:
                    metric.update(exported_pod=f"work-{index}", exported_container="inference",
                                  exported_namespace="business")
                result.append({"metric": metric, "values": points[offset:offset+length]})
                offset += length
        return result, error


class GpuAllocationCollectorTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "GPU_ALLOCATION_INTERVAL_SECONDS": "300",
            "GPU_ALLOCATION_HISTORY_ENABLED": "true",
            "GPU_ALLOCATION_PHYSICAL_RESOURCE_KEY": "nvidia.com/gpu",
            "GPU_ALLOCATION_CLUSTER_NAME": "test-cluster",
            "GPU_ALLOCATION_MONITOR_SCRAPE_INTERVAL_SECONDS": "30",
            "GPU_ALLOCATION_MONITOR_COVERAGE_FRACTION": "0.8",
            "PROMETHEUS_GPU_USAGE_ENABLED": "true",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def build(self, k8s=None, prometheus=None, now=None, vendor="nvidia"):
        with patch.object(collector.K8sClient, "from_config", return_value=k8s or FakeK8s()), \
             patch.object(collector.PrometheusClient, "from_config", return_value=prometheus or FakePrometheus()):
            return collector.build_current_snapshot(now or datetime(2026, 10, 10, 15, 3, 21), vendor=vendor)

    def test_physical_counts_and_capacity_weighted_memory(self):
        snapshot, diagnostics = self.build()
        self.assertEqual(snapshot["gpu_capacity"], 2)
        self.assertEqual(snapshot["gpu_allocatable"], 2)
        self.assertEqual(snapshot["gpu_allocated"], 1)
        self.assertEqual(snapshot["allocation_rate"], 50)
        self.assertEqual(snapshot["gpu_utilization_avg"], 20)
        self.assertEqual(snapshot["gpu_utilization_max"], 60)
        self.assertEqual(snapshot["gpu_memory_utilization"], 25)
        self.assertEqual(snapshot["gpu_active_count"], 2)
        self.assertTrue(snapshot["monitor_valid"])
        self.assertEqual(snapshot["sampled_at"], datetime(2026, 10, 10, 15, 3, 21))
        self.assertEqual(snapshot["sample_slot"], datetime(2026, 10, 10, 15, 0))
        self.assertEqual(snapshot["calculation_version"], "physical-accelerator-v2")
        self.assertEqual(diagnostics["allocation_issues"], [])

    def test_ready_same_scope_excludes_notready_and_unschedulable_numerator(self):
        nodes = [node(), node("offline", 4, ready=False), node("maintenance", 3, unschedulable=True)]
        pods = [pod(), pod("off", "offline", count=4), pod("maint", "maintenance", count=3)]
        snapshot, _ = self.build(FakeK8s(nodes, pods))
        self.assertEqual(snapshot["gpu_capacity"], 9)
        self.assertEqual(snapshot["gpu_allocatable"], 2)
        self.assertEqual(snapshot["gpu_allocated"], 1)
        self.assertFalse(snapshot["monitor_valid"])

    def test_ascend_is_not_physical_nvidia_gpu(self):
        npu = node("npu", 4)
        npu["status"]["capacity"] = {"huawei.com/Ascend310P": "4"}
        npu["status"]["allocatable"] = {"huawei.com/Ascend310P": "4"}
        snapshot, _ = self.build(FakeK8s([node(), npu], [pod()]))
        self.assertEqual(snapshot["gpu_capacity"], 2)

    def test_bound_pending_and_terminating_count_terminal_unbound_excluded(self):
        terminating = pod("term")
        terminating["metadata"]["deletionTimestamp"] = "2026-10-10T06:00:00Z"
        pods = [pod("pending", phase="Pending"), terminating,
                pod("done", phase="Succeeded"), pod("failed", phase="Failed"),
                pod("unbound", node_name="", phase="Pending")]
        snapshot, _ = self.build(FakeK8s(pods=pods))
        self.assertEqual(snapshot["gpu_allocated"], 2)

    def test_init_containers_limits_fallback_sidecars_and_overhead(self):
        item = pod()
        item["spec"]["containers"] = [container(2), container(1, request=False)]
        item["spec"]["initContainers"] = [container(2, restartable=True), container(4),
                                               container(1, restartable=True), container(5)]
        item["spec"]["overhead"] = {"nvidia.com/gpu": "1"}
        self.assertEqual(collector.effective_pod_request(item), 9)

    def test_shared_and_mig_inventory_rejected_not_estimated(self):
        cases = [{"nvidia.com/gpu.replicas": "4"},
                 {"nvidia.com/gpu.sharing-strategy": "time-slicing"},
                 {"nvidia.com/mig.strategy": "mixed"},
                 {"nvidia.com/gpu.product": "RTX-4090-SHARED"}]
        for labels in cases:
            with self.subTest(labels=labels):
                snapshot, diagnostics = self.build(FakeK8s([node(labels=labels)]))
                self.assertFalse(snapshot["allocation_valid"])
                self.assertIsNone(snapshot["gpu_capacity"])
                self.assertIsNone(snapshot["allocation_rate"])
                self.assertTrue(diagnostics["allocation_issues"])

    def test_stale_count_label_reconciles_only_with_complete_whole_gpu_inventory(self):
        k8s = FakeK8s([node("rl3", 6, labels={"nvidia.com/gpu.count": "4"})],
                     [pod("rl3-p", "rl3", count=5)])
        prom = FakePrometheus()
        prom.cards = [("rl3", f"GPU-{index}", 0, 0, 0, 24576) for index in range(6)]
        snapshot, diagnostics = self.build(k8s, prom)
        self.assertEqual(snapshot["gpu_capacity"], 6)
        self.assertEqual(snapshot["gpu_allocated"], 5)
        self.assertTrue(snapshot["allocation_valid"])
        self.assertIn("stale_gpu_count_label_reconciled_by_dcgm", diagnostics["allocation_warnings"])
        prom.cards.pop()
        snapshot, _ = self.build(k8s, prom)
        self.assertFalse(snapshot["allocation_valid"])
        self.assertIsNone(snapshot["gpu_capacity"])

    def test_mig_uuid_cannot_reconcile_stale_physical_count(self):
        k8s = FakeK8s([node(labels={"nvidia.com/gpu.count": "1"})])
        prom = FakePrometheus()
        prom.cards[0] = ("worker", "MIG-a", 10, 20, 25, 100)
        snapshot, _ = self.build(k8s, prom)
        self.assertFalse(snapshot["allocation_valid"])
        self.assertFalse(snapshot["monitor_valid"])

    def test_gpu_identity_must_match_across_monitor_queries(self):
        class DifferentUuidPrometheus(FakePrometheus):
            def query(self, query):
                rows, error = super().query(query)
                if "FB_" in query:
                    for row in rows:
                        row["metric"]["UUID"] += "-different"
                return rows, error
        snapshot, diagnostics = self.build(prometheus=DifferentUuidPrometheus())
        self.assertFalse(snapshot["monitor_valid"])
        self.assertIsNone(snapshot["gpu_memory_utilization"])
        self.assertIn("monitor_gpu_identity_mismatch", diagnostics["monitor_issues"])

    def test_unverified_custom_resource_key_is_invalid_even_when_nodes_lack_it(self):
        with patch.dict(os.environ, {"GPU_ALLOCATION_PHYSICAL_RESOURCE_KEY": "huawei.com/Ascend310P"}):
            snapshot, _ = self.build()
        self.assertFalse(snapshot["allocation_valid"])

    def test_hami_virtual_resources_rejected(self):
        shared = node()
        shared["status"]["capacity"]["nvidia.com/gpucores"] = "200"
        snapshot, _ = self.build(FakeK8s([shared]))
        self.assertFalse(snapshot["allocation_valid"])

    def test_pagination_incomplete_invalid_not_partial_total(self):
        k8s = FakeK8s()
        k8s.continuation = "next-page"
        snapshot, diagnostics = self.build(k8s)
        self.assertFalse(snapshot["allocation_valid"])
        self.assertIn("pods_incomplete_page", diagnostics["allocation_issues"])

    def test_overallocated_node_invalid_even_when_cluster_total_fits(self):
        snapshot, _ = self.build(FakeK8s([node(), node("extra", 4)], [pod(count=3)]))
        self.assertFalse(snapshot["allocation_valid"])

    def test_missing_utilization_keeps_valid_memory(self):
        prom = FakePrometheus()
        prom.missing = 2
        snapshot, _ = self.build(prometheus=prom)
        self.assertIsNone(snapshot["gpu_utilization_avg"])
        self.assertEqual(snapshot["gpu_memory_utilization"], 25)
        self.assertFalse(snapshot["monitor_valid"])
        self.assertTrue(snapshot["allocation_valid"])

    def test_missing_memory_keeps_valid_utilization(self):
        prom = FakePrometheus()
        prom.missing = 4
        snapshot, _ = self.build(prometheus=prom)
        self.assertIsNone(snapshot["gpu_memory_utilization"])
        self.assertEqual(snapshot["gpu_utilization_avg"], 20)
        self.assertFalse(snapshot["monitor_valid"])

    def test_duplicate_exporter_deduplicated_and_unmanaged_ignored(self):
        prom = FakePrometheus()
        prom.duplicate = True
        prom.cards.append(("unmanaged", "GPU-z", 100, 100, 100, 100))
        snapshot, _ = self.build(prometheus=prom)
        self.assertEqual(snapshot["gpu_utilization_avg"], 20)
        self.assertEqual(snapshot["gpu_memory_utilization"], 25)
        self.assertTrue(snapshot["monitor_valid"])

    def test_malformed_inf_nan_monitor_no_crash_or_zero(self):
        prom = FakePrometheus()
        prom.cards[0] = ("worker", "GPU-a", float("inf"), 20, float("nan"), 100)
        snapshot, _ = self.build(prometheus=prom)
        self.assertIsNone(snapshot["gpu_utilization_avg"])
        self.assertIsNone(snapshot["gpu_memory_utilization"])

    def test_zero_allocatable_is_not_zero_rate(self):
        snapshot, _ = self.build(FakeK8s([node(unschedulable=True)], []))
        self.assertTrue(snapshot["allocation_valid"])
        self.assertEqual(snapshot["gpu_allocatable"], 0)
        self.assertEqual(snapshot["gpu_allocated"], 0)
        self.assertIsNone(snapshot["allocation_rate"])

    def test_scheme_b_retention_and_utc_conversion(self):
        self.assertEqual(collector.retention_cutoff(datetime(2026, 10, 10)), datetime(2026, 4, 1))
        self.assertEqual(collector.retention_cutoff(datetime(2026, 1, 10)), datetime(2025, 7, 1))
        snapshot, _ = self.build(now=datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc))
        self.assertEqual(snapshot["sampled_at"], datetime(2026, 10, 1))

    def test_api_read_does_not_save_and_explicit_collection_saves(self):
        with patch.object(collector, "save_snapshot", return_value=None) as save:
            self.build()
            save.assert_not_called()
            with patch.object(collector, "build_current_snapshot", return_value=({"allocation_valid": False}, {})):
                result = collector.collect_and_save_once()
            self.assertTrue(result["saved"])
            save.assert_called_once()

    def test_background_exception_retries_and_cleanup_is_protected(self):
        # Controlled exit after two iterations; no real threads, sleeps or DB.
        with patch.object(collector, "collect_and_save_once", side_effect=[ValueError("bad metric"), {"saved": True}]) as collect, \
             patch.object(collector, "cleanup_snapshots", side_effect=RuntimeError("database")), \
             patch.object(collector.time, "monotonic", return_value=100), \
             patch.object(collector.time, "sleep", side_effect=[None, KeyboardInterrupt]), \
             patch.object(collector._logger, "error"):
            with self.assertRaises(KeyboardInterrupt):
                collector._collector_loop()
            self.assertEqual(collect.call_count, 2)

    def test_dead_thread_can_restart_but_running_thread_cannot_duplicate(self):
        old_thread = Mock()
        old_thread.is_alive.return_value = False
        new_thread = Mock()
        new_thread.is_alive.return_value = True
        with patch.object(collector, "_collector_thread", old_thread), \
             patch.object(collector, "_collector_started", True), \
             patch.object(collector.threading, "Thread", return_value=new_thread):
            self.assertTrue(collector.start_gpu_allocation_collector())
            new_thread.start.assert_called_once()
            self.assertFalse(collector.start_gpu_allocation_collector())

    def test_worker_exit_clears_started_flag(self):
        current = Mock()
        with patch.object(collector, "_collector_thread", current), \
             patch.object(collector, "_collector_started", True), \
             patch.object(collector.threading, "current_thread", return_value=current), \
             patch.object(collector, "_collector_loop", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                collector._collector_worker()
            self.assertFalse(collector._collector_started)

    def test_disabled_collector_does_not_spawn_thread(self):
        with patch.dict(os.environ, {"GPU_ALLOCATION_HISTORY_ENABLED": "false"}), \
             patch.object(collector.threading, "Thread") as thread:
            self.assertFalse(collector.start_gpu_allocation_collector())
            thread.assert_not_called()

    def test_actual_time_and_unique_slot_are_distinct(self):
        first, _ = self.build(now=datetime(2026, 10, 10, 15, 3, 21, 900000))
        second, _ = self.build(now=datetime(2026, 10, 10, 15, 4, 50))
        self.assertEqual(first["sample_slot"], second["sample_slot"])
        self.assertNotEqual(first["sampled_at"], second["sampled_at"])
        self.assertEqual(first["sampled_at"].microsecond, 0)

    def test_queries_anchor_five_minutes_to_actual_time_not_slot(self):
        prom = FakePrometheus()
        with patch.object(prom, "query", wraps=prom.query) as query, \
             patch.dict(os.environ, {"GPU_ALLOCATION_INTERVAL_SECONDS": "60"}):
            snapshot, diagnostics = self.build(prometheus=prom)
        expected = int(snapshot["sampled_at"].replace(tzinfo=collector.LOCAL_TIMEZONE).timestamp())
        self.assertEqual(snapshot["sample_slot"], datetime(2026, 10, 10, 15, 3))
        self.assertEqual(diagnostics["monitor_window_seconds"], 300)
        self.assertTrue(snapshot["monitor_valid"])
        self.assertEqual(query.call_count, 3)
        for call in query.call_args_list:
            self.assertIn("[5m]", call.args[0])
            self.assertTrue(call.args[0].endswith(f"@ {expected}"))
            self.assertNotIn("avg_over_time", call.args[0])

    def test_new_node_with_one_scrape_is_not_complete_monitoring(self):
        class NewlyAddedNode(FakePrometheus):
            def query(self, query):
                rows, error = super().query(query)
                for row in rows:
                    if row["metric"]["Hostname"] == "gpu-176":
                        row["values"] = row["values"][-1:]
                return rows, error
        prom = NewlyAddedNode()
        prom.cards.append(("gpu-176", "GPU-new", 10, 20, 100, 24000))
        snapshot, diagnostics = self.build(FakeK8s([node(), node("gpu-176", 1)]), prom)
        self.assertTrue(snapshot["allocation_valid"])
        self.assertFalse(snapshot["monitor_valid"])
        self.assertIsNone(snapshot["gpu_utilization_avg"])
        self.assertIsNone(snapshot["gpu_memory_utilization"])
        self.assertEqual(diagnostics["monitor_coverage"]["utilization"]["valid_cards"], 2)

    def test_stale_window_is_not_current_monitoring(self):
        class StaleWindow(FakePrometheus):
            def query(self, query):
                rows, error = super().query(query)
                for row in rows:
                    row["values"] = [[timestamp - 120, value] for timestamp, value in row["values"]]
                return rows, error
        snapshot, _ = self.build(prometheus=StaleWindow())
        self.assertFalse(snapshot["monitor_valid"])
        self.assertIsNone(snapshot["gpu_memory_utilization"])

    def test_internal_gap_invalidates_despite_eight_of_ten_points(self):
        class InternalGap(FakePrometheus):
            def query(self, query):
                rows, error = super().query(query)
                if "GPU_UTIL" in query:
                    rows[0]["values"] = rows[0]["values"][:3] + rows[0]["values"][5:]
                return rows, error
        snapshot, _ = self.build(prometheus=InternalGap())
        self.assertIsNone(snapshot["gpu_utilization_avg"])
        self.assertEqual(snapshot["gpu_memory_utilization"], 25)

    def test_conflicting_duplicate_series_is_not_merged_into_completeness(self):
        for conflict in ("value", "timestamp"):
            with self.subTest(conflict=conflict):
                class DuplicateConflict(FakePrometheus):
                    def query(self, query):
                        rows, error = super().query(query)
                        duplicate = deepcopy(rows[0])
                        if conflict == "value":
                            duplicate["values"][0][1] = "99"
                        else:
                            duplicate["values"][0][0] += 1
                        rows.append(duplicate)
                        return rows, error
                snapshot, _ = self.build(prometheus=DuplicateConflict())
                self.assertFalse(snapshot["monitor_valid"])
                self.assertIsNone(snapshot["gpu_utilization_avg"])

    def test_bad_scrape_and_coverage_configuration_use_safe_defaults(self):
        with patch.dict(os.environ, {"GPU_ALLOCATION_MONITOR_SCRAPE_INTERVAL_SECONDS": "1000",
                                    "GPU_ALLOCATION_MONITOR_COVERAGE_FRACTION": "NaN"}):
            snapshot, diagnostics = self.build()
        self.assertTrue(snapshot["monitor_valid"])
        self.assertEqual(diagnostics["monitor_scrape_interval_seconds"], 30)

    def test_fresh_whole_card_identity_reconciles_label_without_complete_window(self):
        class OnePoint(FakePrometheus):
            def query(self, query):
                rows, error = super().query(query)
                for row in rows:
                    row["values"] = row["values"][-1:]
                return rows, error
        snapshot, diagnostics = self.build(FakeK8s([node(labels={"nvidia.com/gpu.count": "1"})]), OnePoint())
        self.assertTrue(snapshot["allocation_valid"])
        self.assertEqual(snapshot["gpu_capacity"], 2)
        self.assertTrue(diagnostics["monitor_coverage"]["memory_total"]["physical_inventory_valid"])
        self.assertFalse(snapshot["monitor_valid"])
        self.assertIsNone(snapshot["gpu_utilization_avg"])
        self.assertIsNone(snapshot["gpu_memory_utilization"])

    def test_business_owner_fragments_reconstruct_one_real_scrape_window(self):
        with patch.dict(os.environ, {"GPU_ALLOCATION_NVIDIA_MONITOR_SCRAPE_INTERVAL_SECONDS": "15"}):
            snapshot, diagnostics = self.build(prometheus=BusinessFragmentPrometheus())
        self.assertTrue(snapshot["monitor_valid"])
        self.assertEqual(snapshot["gpu_utilization_avg"], 20)
        self.assertEqual(snapshot["gpu_memory_utilization"], 25)
        coverage = diagnostics["monitor_coverage"]["memory_total"]
        self.assertEqual(coverage["valid_cards"], 2)
        self.assertEqual(coverage["minimum_temporal_coverage"], 1)

    def test_business_fragments_keep_conflicts_missing_points_and_exporter_identity_checks(self):
        for conflict in ("value", "instance", "job", "pod", "modelName", "gap", "source_missing"):
            with self.subTest(conflict=conflict):
                class BadFragment(BusinessFragmentPrometheus):
                    def query(self, query):
                        rows, error = super().query(query)
                        if conflict == "value":
                            extra = deepcopy(rows[0])
                            extra["metric"]["exported_pod"] = "conflict"
                            extra["values"][0][1] = "99"
                            rows.append(extra)
                        elif conflict == "gap":
                            rows[2]["values"] = rows[2]["values"][:1]
                        elif conflict == "source_missing":
                            for row in rows:
                                row["metric"].pop("instance")
                                row["metric"].pop("job")
                        else:
                            rows[2]["metric"][conflict] = "different-source-or-device"
                        return rows, error
                with patch.dict(os.environ, {"GPU_ALLOCATION_NVIDIA_MONITOR_SCRAPE_INTERVAL_SECONDS": "15"}):
                    snapshot, _ = self.build(prometheus=BadFragment())
                self.assertFalse(snapshot["monitor_valid"])
                self.assertIsNone(snapshot["gpu_utilization_avg"])

    def test_repeated_identical_fragments_do_not_double_count_samples(self):
        class RepeatedFragment(BusinessFragmentPrometheus):
            def query(self, query):
                rows, error = super().query(query)
                return rows + deepcopy(rows), error
        with patch.dict(os.environ, {"GPU_ALLOCATION_NVIDIA_MONITOR_SCRAPE_INTERVAL_SECONDS": "15"}):
            snapshot, diagnostics = self.build(prometheus=RepeatedFragment())
        self.assertTrue(snapshot["monitor_valid"])
        self.assertEqual(snapshot["gpu_utilization_avg"], 20)
        self.assertEqual(diagnostics["monitor_coverage"]["utilization"]["valid_cards"], 2)

    def test_inventory_reconciliation_does_not_depend_on_utilization_availability(self):
        prom = FakePrometheus()
        prom.missing = 2
        snapshot, _ = self.build(FakeK8s([node(labels={"nvidia.com/gpu.count": "1"})]), prom)
        self.assertTrue(snapshot["allocation_valid"])
        self.assertFalse(snapshot["monitor_valid"])
        self.assertIsNone(snapshot["gpu_utilization_avg"])

    def test_stale_or_conflicting_total_memory_cannot_reconcile_inventory(self):
        for conflict in ("stale", "zero", "duplicate"):
            with self.subTest(conflict=conflict):
                class BadInventory(FakePrometheus):
                    def query(self, query):
                        rows, error = super().query(query)
                        if "FB_TOTAL" in query:
                            if conflict == "stale":
                                for row in rows:
                                    row["values"] = [[timestamp-120, value] for timestamp, value in row["values"]]
                            elif conflict == "zero":
                                rows[0]["values"][-1][1] = "0"
                            else:
                                extra = deepcopy(rows[0])
                                extra["metric"]["instance"] = "different-exporter"
                                extra["values"][0][0] += 1
                                rows.append(extra)
                        return rows, error
                snapshot, _ = self.build(FakeK8s([node(labels={"nvidia.com/gpu.count": "1"})]), BadInventory())
                self.assertFalse(snapshot["allocation_valid"])

    def test_instant_values_cannot_stand_in_for_range_coverage(self):
        class InstantOnly(FakePrometheus):
            def query(self, query):
                rows, error = super().query(query)
                for row in rows:
                    row["value"] = row.pop("values")[-1]
                return rows, error
        snapshot, _ = self.build(prometheus=InstantOnly())
        self.assertFalse(snapshot["monitor_valid"])
        self.assertIsNone(snapshot["gpu_memory_utilization"])


if __name__ == "__main__":
    unittest.main()
