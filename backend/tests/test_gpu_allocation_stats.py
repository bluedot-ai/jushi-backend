import unittest
import os
from datetime import datetime, timedelta
from unittest.mock import patch

from backend.modules.resources import gpu_allocation_stats as stats


def sample(at, total=24, allocated=12, **extra):
    return {
        "sampled_at": at, "gpu_capacity": total, "gpu_allocatable": total,
        "gpu_allocated": allocated, "allocation_valid": True,
        "gpu_utilization_avg": None, "gpu_memory_utilization": None,
        "calculation_version": stats.CALCULATION_VERSION,
        "vendor": "all",
        "sample_interval_seconds": 300, **extra,
    }


class GpuAllocationStatsTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 10, 1)

    def test_scheme_b_rolls_across_year_and_leap_month(self):
        self.assertEqual(stats.retention_cutoff(datetime(2026, 10, 10)), datetime(2026, 4, 1))
        self.assertEqual(stats.retention_cutoff(datetime(2026, 2, 28)), datetime(2025, 8, 1))

    def test_allocation_is_ratio_of_card_time_not_average_of_percentages(self):
        rows = [sample(self.start, 16, 8), sample(self.start + timedelta(minutes=5), 24, 24)]
        result = stats.aggregate(rows, self.start, self.start + timedelta(minutes=10))
        self.assertEqual(result["allocation_rate_avg"], 80)
        self.assertEqual(result["allocation_rate_max"], 100)
        self.assertEqual(result["gpu_card_hours"], 2.6667)
        self.assertEqual(result["gpu_capacity_avg"], 20)
        self.assertEqual(result["allocation_completeness"], 100)

    def test_large_gap_never_fills_whole_missing_period(self):
        rows = [sample(self.start), sample(self.start + timedelta(hours=1))]
        result = stats.aggregate(rows, self.start, self.start + timedelta(hours=1, minutes=5))
        self.assertEqual(result["coverage_seconds"]["allocation"], 600)
        self.assertEqual(result["gpu_card_hours"], 2)
        self.assertAlmostEqual(result["allocation_completeness"], 15.385)

    def test_last_sample_never_extrapolates_beyond_one_interval(self):
        result = stats.aggregate([sample(self.start)], self.start, self.start + timedelta(hours=1))
        self.assertEqual(result["coverage_seconds"]["allocation"], 300)
        self.assertEqual(result["gpu_card_hours"], 1)

    def test_zero_allocatable_does_not_create_fake_rate(self):
        result = stats.aggregate([sample(self.start, 0, 0)], self.start, self.start + timedelta(minutes=5))
        self.assertEqual(result["gpu_allocatable_avg"], 0)
        self.assertIsNone(result["allocation_rate_avg"])
        self.assertEqual(result["gpu_card_hours"], 0)

    def test_missing_monitors_do_not_become_zero(self):
        result = stats.aggregate([sample(self.start)], self.start, self.start + timedelta(minutes=5))
        self.assertIsNone(result["gpu_utilization_avg"])
        self.assertIsNone(result["gpu_memory_utilization"])
        self.assertEqual(result["utilization_completeness"], 0)

    def test_monitors_use_previous_window_and_independent_validity(self):
        rows = [sample(self.start + timedelta(minutes=5), allocation_valid=False,
                       gpu_memory_utilization=20, monitor_valid=False)]
        result = stats.aggregate(rows, self.start, self.start + timedelta(minutes=5))
        self.assertIsNone(result["allocation_rate_avg"])
        self.assertEqual(result["gpu_memory_utilization"], 20)
        self.assertIsNone(result["gpu_utilization_avg"])
        self.assertEqual(result["memory_completeness"], 100)

    def test_allocated_and_denominator_must_use_same_valid_pool(self):
        result = stats.aggregate([sample(self.start, 4, 5)], self.start, self.start + timedelta(minutes=5))
        self.assertIsNone(result["allocation_rate_avg"])
        self.assertEqual(result["allocation_completeness"], 0)

    def test_duplicate_rows_do_not_inflate_duration_or_completeness(self):
        row = sample(self.start)
        result = stats.aggregate([row, row, row], self.start, self.start + timedelta(minutes=5))
        self.assertEqual(result["gpu_card_hours"], 1)
        self.assertEqual(result["allocation_completeness"], 100)

    def test_adjacent_monitor_windows_do_not_overlap(self):
        rows = [sample(self.start + timedelta(minutes=5), gpu_utilization_avg=10),
                sample(self.start + timedelta(minutes=6), gpu_utilization_avg=20)]
        result = stats.aggregate(rows, self.start, self.start + timedelta(minutes=6))
        self.assertEqual(result["coverage_seconds"]["utilization"], 360)
        self.assertAlmostEqual(result["gpu_utilization_avg"], 11.6667)

    def test_allocation_intervals_split_exactly_at_month_boundary(self):
        row = sample(self.start - timedelta(minutes=2))
        old = stats.aggregate([row], self.start - timedelta(minutes=5), self.start)
        new = stats.aggregate([row], self.start, self.start + timedelta(minutes=5))
        self.assertEqual(old["coverage_seconds"]["allocation"], 120)
        self.assertEqual(new["coverage_seconds"]["allocation"], 180)

    def test_manual_collections_do_not_inflate_slot_completeness(self):
        rows = [sample(self.start + timedelta(seconds=index)) for index in range(10)]
        result = stats.aggregate(rows, self.start, self.start + timedelta(minutes=10))
        self.assertEqual(result["valid_sample_counts"]["allocation"], 1)
        self.assertEqual(result["allocation_completeness"], 50)

    def test_old_interval_not_reinterpreted_using_current_interval(self):
        rows = [sample(self.start, sample_interval_seconds=60),
                sample(self.start + timedelta(minutes=5), sample_interval_seconds=60)]
        result = stats.aggregate(rows, self.start, self.start + timedelta(minutes=10))
        self.assertEqual(result["expected_samples"], 10)
        self.assertEqual(result["allocation_completeness"], 20)

    def test_interval_change_uses_piecewise_expected_slots(self):
        rows = [sample(self.start + timedelta(minutes=index), sample_interval_seconds=60) for index in range(5)]
        rows += [sample(self.start + timedelta(minutes=5), sample_interval_seconds=300)]
        result = stats.aggregate(rows, self.start, self.start + timedelta(minutes=10))
        self.assertEqual(result["expected_samples"], 6)
        self.assertEqual(result["allocation_completeness"], 100)
        self.assertEqual([item["seconds"] for item in result["sampling_intervals"]], [60, 300])

    def test_previous_monitor_window_splits_at_month_boundary(self):
        at = self.start + timedelta(minutes=2)
        row = sample(at, gpu_utilization_avg=20)
        old = stats.aggregate([row], self.start - timedelta(minutes=5), self.start)
        new = stats.aggregate([row], self.start, self.start + timedelta(minutes=5))
        self.assertEqual(old["coverage_seconds"]["utilization"], 180)
        self.assertEqual(new["coverage_seconds"]["utilization"], 120)

    def test_monitor_window_stays_five_minutes_when_sampling_every_minute(self):
        row = sample(self.start + timedelta(minutes=3), sample_interval_seconds=60,
                     gpu_utilization_avg=20)
        result = stats.aggregate([row], self.start, self.start + timedelta(minutes=5))
        self.assertEqual(result["coverage_seconds"]["utilization"], 180)
        self.assertEqual(result["gpu_utilization_avg"], 20)
        self.assertEqual(result["actual_start_at"], "2026-10-01T00:00:00+08:00")

    def test_null_monitor_future_version_does_not_poison_previous_month(self):
        valid = sample(self.start - timedelta(minutes=5))
        future = sample(self.start + timedelta(minutes=2), calculation_version="future-v2")
        result = stats.aggregate([valid, future], self.start - timedelta(minutes=5), self.start)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["calculation_versions"], [stats.CALCULATION_VERSION])
        self.assertEqual(result["allocation_rate_avg"], 50)

    def test_monitor_at_period_end_has_observation_coverage_metadata(self):
        row = sample(self.start + timedelta(minutes=5), allocation_valid=False,
                     gpu_memory_utilization=20)
        result = stats.aggregate([row], self.start, self.start + timedelta(minutes=5))
        self.assertEqual(result["actual_start_at"], "2026-10-01T00:00:00+08:00")
        self.assertEqual(result["actual_end_at"], "2026-10-01T00:05:00+08:00")

    def test_real_non_aligned_time_not_retroactively_counted_as_slot_start(self):
        at = self.start + timedelta(minutes=3, seconds=21)
        row = sample(at)
        result = stats.aggregate([row], self.start, self.start + timedelta(minutes=5))
        self.assertEqual(result["coverage_seconds"]["allocation"], 99)
        self.assertEqual(result["gpu_card_hours"], 0.33)

    def test_month_boundary_uses_predecessor_but_no_stale_fill(self):
        before = sample(self.start - timedelta(minutes=2))
        after = sample(self.start + timedelta(minutes=3))
        result = stats.aggregate([before, after], self.start, self.start + timedelta(minutes=5))
        self.assertEqual(result["coverage_seconds"]["allocation"], 300)
        stale = stats.aggregate([sample(self.start - timedelta(hours=1))], self.start, self.start + timedelta(minutes=5))
        self.assertIsNone(stale["gpu_card_hours"])

    def test_incompatible_versions_are_explicit_not_silently_averaged(self):
        rows = [sample(self.start), sample(self.start + timedelta(minutes=5), calculation_version="future-v2")]
        result = stats.aggregate(rows, self.start, self.start + timedelta(minutes=10))
        self.assertEqual(result["status"], "mixed_version")
        self.assertIsNone(result["allocation_rate_avg"])
        self.assertEqual(stats.aggregate([rows[-1]], self.start, self.start + timedelta(minutes=10))["status"], "unsupported_version")

    def test_empty_history_remains_null(self):
        result = stats.aggregate([], self.start, self.start + timedelta(days=1))
        self.assertEqual(result["status"], "no_data")
        self.assertIsNone(result["gpu_card_hours"])
        self.assertIsNone(result["allocation_rate_avg"])
        self.assertEqual(result["allocation_completeness"], 0)

    def test_invalid_nonfinite_and_negative_monitors_are_ignored(self):
        rows = [sample(self.start, gpu_utilization_avg=float("inf"), gpu_memory_utilization=-1)]
        result = stats.aggregate(rows, self.start, self.start + timedelta(minutes=5))
        self.assertIsNone(result["gpu_utilization_avg"])
        self.assertIsNone(result["gpu_memory_utilization"])

    @patch.object(stats, "_now", return_value=datetime(2026, 10, 10, 12))
    @patch.object(stats, "load_snapshots", return_value=([], None))
    def test_compare_current_month_elapsed_only_and_empty_change_null(self, load, now):
        result = stats.compare({"base_month": "2026-09", "compare_month": "2026-10"})["data"]
        self.assertTrue(result["comparison"]["partial_month"])
        self.assertEqual(result["comparison"]["period_end"], "2026-10-10T12:00:00+08:00")
        self.assertEqual(result["comparison"]["expected_samples"], 2736)
        self.assertIsNone(result["changes"]["gpu_card_hours"]["percentage"])
        self.assertEqual(result["retention_start"], "2026-04-01")

    @patch.object(stats, "_now", return_value=datetime(2026, 10, 10))
    def test_queries_validate_month_timezone_and_range(self, now):
        for query in (
            {"base_month": "2026-03", "compare_month": "2026-10"},
            {"base_month": "2026-09", "compare_month": "2026-11"},
            {"base_month": "2026-09", "compare_month": "2026-10", "timezone": "UTC"},
            {"base_month": "2026-9", "compare_month": "2026-10"},
        ):
            self.assertEqual(stats.compare(query)["http_status_code"], 400)
        self.assertEqual(stats.trend({"start": "2026-10-11", "end": "2026-10-12"})["http_status_code"], 400)

    @patch.object(stats, "_now", return_value=datetime(2026, 10, 10))
    @patch.object(stats, "load_snapshots", return_value=([], None))
    def test_default_cluster_matches_collector_environment_and_explicit_override(self, load, now):
        with patch.dict(os.environ, {"GPU_ALLOCATION_CLUSTER_NAME": "history-cluster"}):
            result = stats.compare({"base_month": "2026-09", "compare_month": "2026-10"})
            self.assertEqual(result["data"]["cluster_name"], "history-cluster")
            self.assertTrue(all(call.args[0] == "history-cluster" for call in load.call_args_list))
            load.reset_mock()
            result = stats.trend({"start": "2026-10-09", "end": "2026-10-10", "cluster_name": "explicit-cluster"})
            self.assertEqual(result["data"]["cluster_name"], "explicit-cluster")
            self.assertEqual(load.call_args.args[0], "explicit-cluster")

    @patch.object(stats, "_now", return_value=datetime(2026, 10, 10))
    def test_empty_collector_cluster_environment_matches_default(self, now):
        with patch.dict(os.environ, {"GPU_ALLOCATION_CLUSTER_NAME": ""}):
            cluster, _, _ = stats._context({})
            self.assertEqual(cluster, "default")

    @patch.object(stats, "_now", return_value=datetime(2026, 10, 10))
    @patch.object(stats, "load_snapshots")
    def test_default_all_scope_never_double_counts_vendor_rows_or_legacy(self, load, now):
        at = datetime(2026, 9, 1)
        rows = [sample(at, 7, 3, vendor="nvidia"), sample(at, 8, 4, vendor="ascend"),
                sample(at, 15, 7, vendor="all"),
                sample(at, 7, 3, vendor="nvidia", calculation_version="physical-gpu-v1")]
        load.return_value = (rows, None)
        result = stats.compare({"base_month": "2026-09", "compare_month": "2026-09"})["data"]
        self.assertEqual(result["vendor"], "all")
        self.assertEqual(result["available_vendors"], ["all", "nvidia", "ascend"])
        self.assertEqual(result["base"]["gpu_capacity_avg"], 15)
        self.assertEqual(result["base"]["gpu_allocated_avg"], 7)
        self.assertEqual(result["base"]["calculation_versions"], ["physical-accelerator-v2"])
        self.assertTrue(all(call.kwargs["vendor"] == "all" for call in load.call_args_list))

    @patch.object(stats, "_now", return_value=datetime(2026, 10, 10))
    @patch.object(stats, "load_snapshots")
    def test_pure_ascend_history_and_arm_architecture_are_supported(self, load, now):
        at = datetime(2026, 9, 1, 0, 5)
        load.return_value = ([sample(at, 16, 8, vendor="ascend", architecture="arm64", gpu_utilization_avg=30)], None)
        result = stats.compare({"base_month": "2026-09", "compare_month": "2026-09", "vendor": "ascend"})["data"]
        self.assertEqual(result["base"]["gpu_capacity_avg"], 16)
        self.assertEqual(result["base"]["allocation_rate_avg"], 50)
        self.assertEqual(result["base"]["gpu_utilization_avg"], 30)
        self.assertEqual(load.call_args.kwargs["vendor"], "ascend")

    @patch.object(stats, "_now", return_value=datetime(2026, 10, 10))
    @patch.object(stats, "load_snapshots")
    def test_legacy_nvidia_only_history_readable_but_not_compared_to_v2(self, load, now):
        old = sample(datetime(2026, 8, 1), 8, 4, vendor="nvidia", calculation_version="physical-gpu-v1")
        new = sample(datetime(2026, 9, 1), 8, 6, vendor="nvidia")
        load.side_effect = [([old], None), ([new], None)]
        result = stats.compare({"base_month": "2026-08", "compare_month": "2026-09", "vendor": "nvidia"})["data"]
        self.assertEqual(result["base"]["status"], "ok")
        self.assertEqual(result["base"]["allocation_rate_avg"], 50)
        self.assertEqual(result["comparison"]["allocation_rate_avg"], 75)
        self.assertFalse(result["comparison_compatible"])
        self.assertEqual(result["comparison_warning"], "calculation_version_mismatch")
        self.assertTrue(all(change["absolute"] is None for change in result["changes"].values()))

    @patch.object(stats, "_now", return_value=datetime(2026, 10, 10))
    @patch.object(stats, "load_snapshots", return_value=([], None))
    def test_vendor_validation_and_trend_metadata(self, load, now):
        result = stats.trend({"start": "2026-10-01", "end": "2026-10-02", "vendor": "ascend"})["data"]
        self.assertEqual(result["vendor"], "ascend")
        self.assertEqual(load.call_args.kwargs["vendor"], "ascend")
        error = stats.compare({"base_month": "2026-09", "compare_month": "2026-10", "vendor": "huawei"})
        self.assertEqual(error["http_status_code"], 400)

    @patch.object(stats, "_now", return_value=datetime(2026, 10, 10))
    @patch.object(stats, "load_snapshots")
    def test_missing_history_does_not_claim_a_version_change(self, load, now):
        row = sample(datetime(2026, 9, 1), 8, 4, vendor="ascend")
        load.side_effect = [([], None), ([row], None)]
        result = stats.compare({"base_month": "2026-08", "compare_month": "2026-09", "vendor": "ascend"})["data"]
        self.assertEqual(result["base"]["status"], "no_data")
        self.assertIsNone(result["comparison_warning"])
        self.assertIsNone(result["changes"]["allocation_rate_avg"]["absolute"])

    @patch.object(stats, "_now", return_value=datetime(2026, 10, 10, 12))
    @patch.object(stats, "load_snapshots", return_value=([], None))
    def test_daily_trend_returns_null_buckets_and_metadata(self, load, now):
        result = stats.trend({"start": "2026-10-09", "end": "2026-10-11"})["data"]
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["date"], "2026-10-09")
        self.assertEqual(result["items"][1]["period_end"], "2026-10-10T12:00:00+08:00")
        self.assertIsNone(result["items"][0]["allocation_rate_avg"])

    @patch.object(stats, "_now", return_value=datetime(2026, 10, 10, 12))
    @patch.object(stats, "load_snapshots", return_value=([], "数据库不可用"))
    def test_database_error_is_service_unavailable(self, load, now):
        result = stats.compare({"base_month": "2026-09", "compare_month": "2026-10"})
        self.assertEqual(result["http_status_code"], 503)

    @patch.object(stats, "_now", return_value=datetime(2026, 10, 1, 0, 5))
    @patch.object(stats, "load_snapshots")
    def test_future_sample_never_contributes_to_current_month(self, load, now):
        future = sample(self.start + timedelta(minutes=6), gpu_utilization_avg=90)
        load.return_value = ([future], None)
        result = stats.compare({"base_month": "2026-10", "compare_month": "2026-10"})["data"]
        self.assertIsNone(result["comparison"]["gpu_utilization_avg"])
        self.assertEqual(result["comparison"]["status"], "no_data")

    @patch.object(stats, "_now", return_value=datetime(2026, 10, 10))
    @patch.object(stats, "load_snapshots")
    def test_change_reports_pp_and_relative_percentage(self, load, now):
        base = datetime(2026, 8, 1)
        other = datetime(2026, 9, 1)
        load.side_effect = [([sample(base, 20, 10)], None), ([sample(other, 20, 15)], None)]
        change = stats.compare({"base_month": "2026-08", "compare_month": "2026-09"})["data"]["changes"]["allocation_rate_avg"]
        self.assertEqual(change["absolute"], 25)
        self.assertEqual(change["percentage"], 50)
        self.assertEqual(change["unit"], "pp")


if __name__ == "__main__":
    unittest.main()
