import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import backend.modules.resources.recommendation as recommendation_module
import backend.modules.resources.trend as trend_module
import backend.modules.resources.trend_cache as trend_cache_module
from backend.modules.resources import service
from backend.modules.resources import metrics, parser, repository, views
from backend.modules.resources.constants import METRIC_SOURCE


def _context():
    return {
        "client": object(),
        "namespace": "test-namespace",
        "cluster": {"name": "test-cluster"},
        "raw_nodes": [],
        "pods": [],
        "pod_allocated_by_node": {},
        "allocatable": {
            "cpu": 4000,
            "memory": 8 * 1024 ** 3,
            "nvidia.com/gpu": 2,
        },
        "allocated": {
            "cpu": 1000,
            "memory": 2 * 1024 ** 3,
            "nvidia.com/gpu": 1,
        },
        "collected_at": "2026-07-20 12:00:00",
        "metric_source": METRIC_SOURCE,
        "diagnostics": {
            "nodes_error": None,
            "pod_error": None,
            "resource_source": METRIC_SOURCE,
            "usage_metric_ready": False,
            "usage_metric_source": "not_configured",
        },
    }


class ResourceQuantityTests(unittest.TestCase):
    def test_cpu_quantity(self):
        self.assertEqual(parser._parse_cpu_m("2"), 2000)
        self.assertEqual(parser._parse_cpu_m("250m"), 250)
        self.assertEqual(parser._parse_cpu_m(None), 0)

    def test_memory_quantity(self):
        self.assertEqual(parser._parse_memory_bytes("4Gi"), 4 * 1024 ** 3)
        self.assertEqual(parser._parse_memory_bytes("512Mi"), 512 * 1024 ** 2)
        self.assertEqual(parser._parse_memory_bytes("invalid"), 0)

    def test_gpu_memory_quantity(self):
        self.assertEqual(parser._parse_gpumem_mib("24Gi"), 24 * 1024)
        self.assertEqual(parser._parse_gpumem_mib("1024Mi"), 1024)
        self.assertEqual(parser._parse_gpumem_mib("4096"), 4096)


class ResourceContractTests(unittest.TestCase):
    @patch.object(views, "_save_resource_snapshot", return_value=True)
    @patch.object(views, "_resource_context")
    def test_summary_contract(self, resource_context, _save_snapshot):
        resource_context.return_value = (_context(), None)

        result = service.summary({})

        self.assertTrue(result["is_success"])
        self.assertEqual(result["namespace"], "test-namespace")
        self.assertEqual(result["collected_at"], "2026-07-20 12:00:00")
        self.assertIn("health", result)
        self.assertIn("cards", result)
        self.assertEqual(result["cards"]["physical_gpu_total"], 2)
        self.assertEqual(result["cards"]["physical_gpu_used"], 1)
        _save_snapshot.assert_called_once_with("summary", result)

    @patch.object(views, "_resource_context")
    def test_nodes_contract_with_empty_cluster(self, resource_context):
        resource_context.return_value = (_context(), None)

        result = service.nodes({})

        self.assertTrue(result["is_success"])
        self.assertEqual(result["namespace"], "test-namespace")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["total"], 0)

    @patch.object(views, "_node_card_rows", return_value=[])
    @patch.object(views, "_resource_context")
    def test_gpus_collects_resource_context_once(self, resource_context, node_rows):
        resource_context.return_value = (_context(), None)

        result = service.gpus({})

        self.assertTrue(result["is_success"])
        resource_context.assert_called_once_with({})
        node_rows.assert_called_once()

    @patch.object(views, "_save_resource_snapshot", return_value=True)
    @patch.object(recommendation_module, "_node_card_rows", return_value=[])
    @patch.object(recommendation_module, "_resource_context")
    def test_recommendation_collects_resource_context_once(
        self,
        resource_context,
        node_rows,
        _save_snapshot,
    ):
        resource_context.return_value = (_context(), None)

        result = service.recommendation({})

        self.assertTrue(result["is_success"])
        resource_context.assert_called_once_with({})
        node_rows.assert_called_once()

    @patch.object(metrics, "_prometheus_query")
    def test_prometheus_vector_ignores_rows_without_node(self, query):
        query.return_value = ([
            {"metric": {}, "value": [0, "12"]},
            {"metric": {"node": "worker-1"}, "value": [0, "8"]},
        ], None)

        values, error = metrics._prometheus_vector_by_node("up")

        self.assertIsNone(error)
        self.assertEqual(values, {"worker-1": 8.0})

    @patch.object(repository, "_snapshot_enabled", return_value=False)
    def test_snapshot_disabled_does_not_write(self, _snapshot_enabled):
        self.assertFalse(repository._save_resource_snapshot("summary", {"value": 1}))


class ResourceTrendTests(unittest.TestCase):
    def test_range_configuration_covers_complete_window(self):
        expected = {
            "1h": (60, 60),
            "24h": (15 * 60, 96),
            "7d": (60 * 60, 168),
        }

        for range_value, (bucket_seconds, bucket_count) in expected.items():
            config = trend_module.TREND_RANGE_CONFIG[range_value]
            self.assertEqual(config["bucket_seconds"], bucket_seconds)
            self.assertEqual(
                int(config["duration"].total_seconds() / bucket_seconds),
                bucket_count,
            )

    def test_bucket_builder_fills_missing_intervals_with_nulls(self):
        start_time = datetime(2026, 7, 21, 10, 0, 0)
        end_time = start_time + timedelta(minutes=3)
        rows = [
            {
                "bucket_no": 0,
                "last_sample_at": start_time + timedelta(seconds=50),
                "sample_count": 5,
                "gpu_alloc_percent": 8,
                "gpu_mem_alloc_percent": 1,
                "gpu_mem_usage_percent_avg": 1.28,
                "gpu_mem_usage_percent_max": 1.31,
                "vgpu_alloc_percent": 0,
                "usage_metric_ready": 1,
            },
            {
                "bucket_no": 2,
                "last_sample_at": start_time + timedelta(minutes=2, seconds=50),
                "sample_count": 4,
                "gpu_alloc_percent": 9,
                "gpu_mem_alloc_percent": 2,
                "gpu_mem_usage_percent_avg": 1.46,
                "gpu_mem_usage_percent_max": 1.52,
                "vgpu_alloc_percent": 1,
                "usage_metric_ready": 1,
            },
        ]

        items = trend_module._build_trend_items(
            rows, "1h", start_time, end_time, 60
        )

        self.assertEqual(len(items), 3)
        self.assertFalse(items[0]["data_gap"])
        self.assertEqual(items[0]["gpu_mem_usage_percent"], 1.28)
        self.assertTrue(items[1]["data_gap"])
        self.assertIsNone(items[1]["gpu_alloc_percent"])
        self.assertEqual(items[1]["sample_count"], 0)
        self.assertFalse(items[2]["data_gap"])

    def test_24h_trend_returns_96_buckets_and_raw_count(self):
        end_time = datetime(2026, 7, 21, 12, 0, 0)
        start_time = end_time - timedelta(hours=24)
        bucket_result = {
            "items": [{
                "bucket_no": 95,
                "last_sample_at": end_time - timedelta(seconds=10),
                "sample_count": 88,
                "gpu_alloc_percent": 8,
                "gpu_mem_alloc_percent": 1,
                "gpu_mem_usage_percent_avg": 1.2836,
                "gpu_mem_usage_percent_max": 1.4,
                "vgpu_alloc_percent": 0,
                "usage_metric_ready": 1,
            }],
            "raw_snapshot_count": 8428,
            "actual_start_at": start_time + timedelta(seconds=5),
            "actual_end_at": end_time - timedelta(seconds=10),
            "error": None,
        }

        with patch.object(
            trend_module,
            "_trend_window",
            return_value=(
                "24h",
                trend_module.TREND_RANGE_CONFIG["24h"],
                start_time,
                end_time,
            ),
        ), patch.object(
            trend_module,
            "_load_resource_trend_buckets",
            return_value=bucket_result,
        ):
            result = trend_module._build_trend_response("24h")

        self.assertTrue(result["is_success"])
        self.assertEqual(result["expected_bucket_count"], 96)
        self.assertEqual(result["returned_point_count"], 96)
        self.assertEqual(result["raw_snapshot_count"], 8428)
        self.assertEqual(result["snapshot_count"], 8428)
        self.assertEqual(result["data_gap_count"], 95)
        self.assertTrue(result["downsampled"])
        self.assertEqual(result["items"][-1]["gpu_mem_usage_percent"], 1.28)

    def test_repository_query_has_end_bound_and_no_limit(self):
        start_time = datetime(2026, 7, 20, 12, 0, 0)
        end_time = start_time + timedelta(hours=24)
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.return_value = cursor

        with patch.object(repository, "get_connection", return_value=conn):
            result = repository._load_resource_trend_buckets(
                "summary", start_time, end_time, 15 * 60
            )

        sql, params = cursor.execute.call_args.args
        self.assertNotIn("LIMIT", sql.upper())
        self.assertIn("created_at >= %s", sql)
        self.assertIn("created_at < %s", sql)
        self.assertIn("ROW_NUMBER() OVER", sql)
        self.assertEqual(
            params,
            (start_time, 15 * 60, "summary", start_time, end_time),
        )
        self.assertEqual(result["raw_snapshot_count"], 0)


class ResourceTrendCacheTests(unittest.TestCase):
    def setUp(self):
        self.original_builder = trend_cache_module._cache_builder
        with trend_cache_module._cache_lock:
            self.original_state = {
                key: dict(value)
                for key, value in trend_cache_module._cache_state.items()
            }
            for state in trend_cache_module._cache_state.values():
                state.update({
                    "data": None,
                    "generated_at": None,
                    "refreshing": False,
                    "last_error": None,
                    "last_duration_seconds": None,
                })

    def tearDown(self):
        trend_cache_module._cache_builder = self.original_builder
        with trend_cache_module._cache_lock:
            for key, state in self.original_state.items():
                trend_cache_module._cache_state[key].update(state)

    def test_missing_7d_cache_returns_warming_without_running_query(self):
        with patch.object(
            trend_module, "_build_trend_response"
        ) as build_response, patch.object(
            trend_module, "trigger_trend_cache_refresh", return_value=True
        ) as trigger_refresh:
            result = trend_module.trend({"range": "7d"})

        build_response.assert_not_called()
        trigger_refresh.assert_called_once_with("7d")
        self.assertTrue(result["is_success"])
        self.assertFalse(result["cache_ready"])
        self.assertEqual(result["cache_status"], "warming")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["retry_after_seconds"], 1)

    def test_cached_24h_response_is_returned_without_running_query(self):
        trend_cache_module._cache_builder = lambda range_value: {
            "is_success": True,
            "range": range_value,
            "items": [{"bucket_no": 0}],
        }
        self.assertTrue(trend_cache_module._refresh_trend_cache("24h"))

        with patch.object(trend_module, "_build_trend_response") as build_response:
            result = trend_module.trend({"range": "24h"})

        build_response.assert_not_called()
        self.assertTrue(result["cache_hit"])
        self.assertTrue(result["cache_ready"])
        self.assertEqual(result["cache_refresh_seconds"], 900)
        self.assertEqual(result["items"], [{"bucket_no": 0}])

    def test_refresh_overwrites_previous_payload_instead_of_appending(self):
        marker = {"value": 1}

        def build_response(range_value):
            return {
                "is_success": True,
                "range": range_value,
                "items": [{"marker": marker["value"]}],
            }

        trend_cache_module._cache_builder = build_response
        self.assertTrue(trend_cache_module._refresh_trend_cache("7d"))
        marker["value"] = 2
        self.assertTrue(trend_cache_module._refresh_trend_cache("7d"))

        result = trend_cache_module.get_cached_trend("7d")
        self.assertEqual(result["items"], [{"marker": 2}])
        self.assertEqual(result["cache_refresh_seconds"], 3600)

    def test_failed_refresh_preserves_last_successful_payload(self):
        trend_cache_module._cache_builder = lambda range_value: {
            "is_success": True,
            "range": range_value,
            "items": [{"marker": "last-good"}],
        }
        self.assertTrue(trend_cache_module._refresh_trend_cache("7d"))

        def fail_build(_range_value):
            raise RuntimeError("database unavailable")

        trend_cache_module._cache_builder = fail_build
        self.assertFalse(trend_cache_module._refresh_trend_cache("7d"))

        result = trend_cache_module.get_cached_trend("7d")
        self.assertEqual(result["items"], [{"marker": "last-good"}])
        self.assertTrue(result["cache_last_error"])

    def test_1h_bypasses_trend_cache(self):
        expected = {"is_success": True, "range": "1h", "items": []}
        with patch.object(
            trend_module, "_build_trend_response", return_value=expected
        ) as build_response, patch.object(
            trend_module, "get_cached_trend"
        ) as get_cached:
            result = trend_module.trend({"range": "1h"})

        build_response.assert_called_once_with("1h")
        get_cached.assert_not_called()
        self.assertEqual(result["cache_status"], "bypass")


if __name__ == "__main__":
    unittest.main()

