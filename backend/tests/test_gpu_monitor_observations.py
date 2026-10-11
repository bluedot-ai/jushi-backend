"""Display-only recent values cannot weaken full-window historical monitoring."""

import os
import unittest
from copy import deepcopy
from datetime import datetime
from unittest.mock import patch

from backend.modules.resources import gpu_allocation_collector as collector
from backend.modules.resources import gpu_monitor_observations as observations
from backend.modules.resources.gpu_allocation_repository import SNAPSHOT_FIELDS
from backend.tests.test_gpu_allocation_collector import FakeK8s, FakePrometheus, node
from backend.tests.test_gpu_allocation_ascend import MixedPrometheus, ascend_node


NOW = 1791638400


def matrix(vendor="ascend", node_name="npu", age=95, count=2):
    fields = {}
    for name, value in (("utilization", 0), ("memory_used", 25), ("memory_total", 100)):
        fields[name] = []
        for index in range(count):
            metric = {"node": node_name, "instance": "exporter:8082", "job": "exporter"}
            if vendor == "ascend":
                metric.update(id=str(index), pcie_bus_info=f"0000:0{index+1}:00.0", vdie_id=f"npu-{index}")
            else:
                metric.update(UUID=f"GPU-{index}")
            fields[name].append({"metric": {"__name__": name, **metric},
                                 "values": [[NOW-age-15, str(value)], [NOW-age, str(value)]]})
    return fields


class LatestObservationTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            "PROMETHEUS_GPU_USAGE_ENABLED": "true",
            "GPU_ALLOCATION_NVIDIA_MONITOR_SCRAPE_INTERVAL_SECONDS": "30",
            "GPU_ALLOCATION_ASCEND_MONITOR_SCRAPE_INTERVAL_SECONDS": "30",
            "GPU_ALLOCATION_NVIDIA_MEMORY_UNIT": "MiB", "GPU_ALLOCATION_ASCEND_MEMORY_UNIT": "MB",
            "GPU_ALLOCATION_ASCEND_PHYSICAL_RESOURCE_KEYS": "huawei.com/Ascend310P",
            "GPU_ALLOCATION_PHYSICAL_RESOURCE_KEY": "nvidia.com/gpu",
            "GPU_ALLOCATION_MONITOR_COVERAGE_FRACTION": "0.8",
        })
        env.start()
        self.addCleanup(env.stop)

    def latest(self, rows=None, inventory=None, vendor="ascend", **kwargs):
        return observations.latest_observations(rows if rows is not None else matrix(vendor),
                                               inventory if inventory is not None else {"npu": 2}, NOW, vendor, **kwargs)

    def test_site_two_delayed_cards_out_of_six_are_displayable_not_complete(self):
        result = self.latest(inventory={"npu": 2, "offline": 4})
        for name, value in (("utilization", 0), ("memory", 25)):
            metric = result[name]
            self.assertEqual(metric["value"], value)
            self.assertEqual((metric["expected_cards"], metric["observed_cards"], metric["missing_cards"]), (6, 2, 4))
            self.assertEqual((metric["delayed_cards"], metric["fresh_cards"]), (2, 0))
            self.assertEqual(metric["maximum_age_seconds"], 95)
            self.assertEqual(metric["status"], "partial_delayed")
            self.assertEqual(metric["nodes"][1]["node_name"], "offline")
            self.assertEqual(metric["nodes"][1]["observed_cards"], 0)
            self.assertIn("missing_samples", metric["issues"])

    def test_original_timestamp_not_evaluation_or_ingestion_time(self):
        result = self.latest()
        self.assertEqual(result["memory"]["latest_sample_at"], observations._iso(NOW-95))
        self.assertNotEqual(result["memory"]["latest_sample_at"], observations._iso(NOW))

    def test_fresh_one_point_is_latest_observation_not_five_minute_average(self):
        rows = matrix(age=0)
        for data in rows.values():
            for row in data:
                row["values"] = row["values"][-1:]
        result = self.latest(rows)
        self.assertEqual(result["utilization"]["status"], "complete")
        self.assertEqual(result["mode"], "latest_observation")

    def test_latest_not_average_and_zero_is_real(self):
        rows = matrix(age=0)
        rows["utilization"][0]["values"][0][1] = "100"
        self.assertEqual(self.latest(rows)["utilization"]["value"], 0)

    def test_lookback_boundary_future_and_nonfinite_points_are_not_published(self):
        for timestamp, value in ((NOW-300, "0"), (NOW+1, "0"), (NOW, "NaN"), (NOW, "101"), (NOW, "-1")):
            with self.subTest(timestamp=timestamp, value=value):
                rows = matrix()
                for row in rows["utilization"]:
                    row["values"] = [[timestamp, value]]
                self.assertIsNone(self.latest(rows)["utilization"]["value"])

    def test_separate_coverage_per_metric_and_unmatched_memory_excluded(self):
        rows = matrix(age=0)
        rows["memory_used"] = rows["memory_used"][:1]
        result = self.latest(rows)
        self.assertEqual(result["utilization"]["observed_cards"], 2)
        self.assertEqual(result["memory"]["observed_cards"], 1)
        self.assertEqual(result["memory"]["status"], "partial")

    def test_bad_card_does_not_hide_other_valid_card(self):
        rows = matrix()
        rows["utilization"][0]["values"][0][1] = "-1"
        self.assertEqual(self.latest(rows)["utilization"]["observed_cards"], 1)

    def test_source_conflict_is_not_stitched_or_counted_twice(self):
        rows = matrix()
        extra = deepcopy(rows["utilization"][0])
        extra["metric"]["instance"] = "other:8082"
        extra["values"][-1][1] = "30"
        rows["utilization"].append(extra)
        result = self.latest(rows)
        self.assertEqual(result["utilization"]["observed_cards"], 1)
        self.assertIn("conflicting_monitor_sources", result["utilization"]["issues"])

    def test_identical_replicas_and_ownership_fragments_keep_one_card(self):
        rows = matrix()
        extra = deepcopy(rows["utilization"][0])
        extra["metric"]["exported_pod"] = "inference"
        rows["utilization"].append(extra)
        self.assertEqual(self.latest(rows)["utilization"]["observed_cards"], 2)

    def test_ownership_fragments_without_exporter_identity_are_not_merged(self):
        rows = matrix()
        for row in rows["utilization"]:
            row["metric"].pop("instance")
            row["metric"].pop("job")
        extra = deepcopy(rows["utilization"][0])
        extra["metric"]["exported_pod"] = "inference"
        rows["utilization"].append(extra)
        self.assertEqual(self.latest(rows)["utilization"]["observed_cards"], 1)

    def test_inventory_overcount_virtual_or_missing_identity_not_allowed(self):
        for modification in ("overcount", "virtual", "identity", "uuid_collision", "id_collision"):
            with self.subTest(modification=modification):
                rows = matrix()
                if modification == "overcount":
                    rows = matrix(count=3)
                elif modification == "virtual":
                    for row in rows["utilization"]:
                        row["metric"]["is_virtual"] = "true"
                elif modification == "identity":
                    for row in rows["utilization"]:
                        row["metric"].pop("id")
                        row["metric"].pop("pcie_bus_info")
                elif modification == "uuid_collision":
                    rows["utilization"][1]["metric"]["vdie_id"] = "npu-0"
                else:
                    rows["utilization"][1]["metric"]["id"] = "0"
                self.assertIsNone(self.latest(rows)["utilization"]["value"])

    def test_memory_source_identity_age_value_and_unit_validation(self):
        for modification in ("uuid", "source", "age", "overused", "zero_total", "unit"):
            with self.subTest(modification=modification):
                rows = matrix()
                if modification == "uuid":
                    for row in rows["memory_total"]:
                        row["metric"]["vdie_id"] += "-other"
                elif modification == "source":
                    for row in rows["memory_total"]:
                        row["metric"]["instance"] = "other:8082"
                elif modification == "age":
                    for row in rows["memory_used"]:
                        row["values"] = [[NOW-200, "25"]]
                elif modification == "overused":
                    for row in rows["memory_used"]:
                        row["values"][-1][1] = "101"
                elif modification == "zero_total":
                    for row in rows["memory_total"]:
                        row["values"][-1][1] = "0"
                with patch.dict(os.environ, {"GPU_ALLOCATION_ASCEND_MEMORY_UNIT": "bad" if modification == "unit" else "MB"}):
                    self.assertIsNone(self.latest(rows)["memory"]["value"])

    def test_query_failures_and_unknown_inventory_explicit(self):
        failed = self.latest(errors=("utilization",))
        self.assertIsNone(failed["utilization"]["value"])
        self.assertIn("query_failed", failed["utilization"]["issues"])
        unknown = self.latest({}, {}, known=False)
        self.assertIsNone(unknown["utilization"]["expected_cards"])
        self.assertEqual(unknown["utilization"]["status"], "unavailable")

    def test_cross_vendor_observed_subset_byte_weighting(self):
        nvidia = self.latest(matrix("nvidia", "gpu", age=0), {"gpu": 2}, "nvidia")
        ascend = self.latest(inventory={"npu": 2, "offline": 4})
        aggregate = observations.combine_observations([nvidia, ascend])
        self.assertEqual(aggregate["memory"]["value"], 25)
        self.assertEqual(aggregate["memory"]["observed_cards"], 4)
        self.assertEqual(aggregate["memory"]["expected_cards"], 8)
        self.assertAlmostEqual(aggregate["memory"]["_denominator"], 200 * 1024**2 + 200 * 1000**2)
        for name in ("utilization", "memory"):
            self.assertNotIn("_numerator", observations.public_observations(aggregate)[name])

    def test_six_ascend_nodes_have_independent_partial_coverage(self):
        rows = {name: [] for name in ("utilization", "memory_used", "memory_total")}
        inventory = {f"node-{index}": 2 for index in range(6)}
        for index in range(5):
            for name, data in matrix(node_name=f"node-{index}", age=0).items():
                for row in data:
                    row["metric"]["vdie_id"] += f"-node-{index}"
                rows[name].extend(data)
        result = self.latest(rows, inventory)
        self.assertEqual(result["memory"]["expected_cards"], 12)
        self.assertEqual(result["memory"]["observed_cards"], 10)
        self.assertEqual(len(result["memory"]["nodes"]), 6)

    def test_current_fallback_reuses_queries_and_cannot_enter_history(self):
        class SitePrometheus(MixedPrometheus):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def query(self, query):
                self.calls += 1
                rows, error = super().query(query)
                if "npu_chip_info" in query:
                    for row in rows:
                        row["values"] = [[point[0]-95, point[1]] for point in row["values"] if point[0]-95 > int(query.rsplit("@", 1)[1])-300]
                return rows, error

        prom = SitePrometheus()
        prom.cards = [("gpu-main", f"GPU-site-{index}", 0, 0, 25, 100) for index in range(6)] + [
            ("gpu-new", "GPU-site-6", 0, 0, 25, 100)]
        k8s = FakeK8s([node("gpu-main", 6), node("gpu-new", 1), ascend_node(),
                      ascend_node("offline", count=4, ready=False)], [])
        with patch.object(collector.K8sClient, "from_config", return_value=k8s), \
             patch.object(collector.PrometheusClient, "from_config", return_value=prom):
            current, _ = collector.build_current_snapshot(datetime(2026, 10, 10, 16), include_observations=True)
            self.assertEqual(prom.calls, 6)
            self.assertIsNone(current["gpu_utilization_avg"])
            self.assertFalse(current["monitor_valid"])
            self.assertEqual(current["observed_monitor"]["utilization"]["observed_cards"], 9)
            self.assertEqual(current["observed_monitor"]["utilization"]["expected_cards"], 13)
            self.assertEqual(current["vendors"][1]["observed_monitor"]["utilization"]["maximum_age_seconds"], 95)
            self.assertTrue(current["vendors"][0]["monitor_valid"])
            self.assertFalse(current["vendors"][1]["monitor_valid"])
            for row in [current, *current["vendors"]]:
                for name in ("utilization", "memory"):
                    self.assertNotIn("_numerator", row["observed_monitor"][name])
            historical, _ = collector.build_current_snapshot(datetime(2026, 10, 10, 16))
            self.assertNotIn("observed_monitor", historical)
            self.assertNotIn("observed_monitor", SNAPSHOT_FIELDS)
            self.assertIsNone(historical["gpu_utilization_avg"])

    def test_disabled_monitor_does_not_query_or_fabricate_observations(self):
        with patch.dict(os.environ, {"PROMETHEUS_GPU_USAGE_ENABLED": "false"}), \
             patch.object(collector.K8sClient, "from_config", return_value=FakeK8s([ascend_node()], [])), \
             patch.object(collector.PrometheusClient, "from_config") as prom:
            result, _ = collector.build_current_snapshot(datetime(2026, 10, 10, 16), "ascend", include_observations=True)
        prom.assert_not_called()
        self.assertTrue(result["allocation_valid"])
        self.assertIsNone(result["observed_monitor"]["memory"]["value"])
        self.assertEqual(result["observed_monitor"]["memory"]["expected_cards"], 2)


if __name__ == "__main__":
    unittest.main()
