import unittest
from unittest.mock import patch

from backend.modules.resources import node_gpu, service


def _instant_row(labels, value):
    return {"metric": labels, "value": [100, str(value)]}


def _matrix_row(labels, values):
    return {"metric": labels, "values": [[timestamp, str(value)] for timestamp, value in values]}


class _FakeClient:
    def __init__(self):
        self.range_calls = []

    def query(self, promql):
        nvidia = {
            "node": "worker-1",
            "UUID": "gpu-a",
            "gpu": "0",
            "device": "nvidia0",
            "modelName": "NVIDIA Test",
        }
        ascend = {
            "node": "worker-1",
            "vdie_id": "npu-a",
            "id": "2",
            "pcie_bus_info": "0000:01:00.0",
            "model_name": "Ascend Test",
        }
        if "DCGM_FI_DEV_FB_TOTAL" in promql:
            return [_instant_row(nvidia, 24576)], None
        if "DCGM_FI_DEV_FB_USED" in promql:
            return [_instant_row(nvidia, 12288)], None
        if "DCGM_FI_DEV_GPU_UTIL" in promql:
            return [_instant_row(nvidia, 25)], None
        if "npu_chip_info_total_memory" in promql:
            return [_instant_row(ascend, 32768)], None
        if "npu_chip_info_used_memory" in promql:
            return [_instant_row(ascend, 4096)], None
        if "npu_chip_info_utilization" in promql:
            return [_instant_row(ascend, 10)], None
        return [], None

    def query_range(self, promql, start, end, step):
        self.range_calls.append((promql, start, end, step))
        if "DCGM" in promql:
            return [_matrix_row({
                "node": "worker-1",
                "UUID": "gpu-a",
                "gpu": "0",
                "device": "nvidia0",
                "modelName": "NVIDIA Test",
            }, [(end - step, 5), (end, 20)])], None
        return [], None


class NodeGpuTests(unittest.TestCase):
    def test_node_name_validation_rejects_promql_injection(self):
        value, error = node_gpu.validate_node_name('worker-1"} or up')

        self.assertEqual(value, "")
        self.assertEqual(error, "Invalid node name")

    def test_realtime_details_merge_nvidia_and_ascend_cards(self):
        client = _FakeClient()
        with patch.object(node_gpu, "_client", return_value=(client, None)):
            payload = node_gpu.node_gpu_details("worker-1", {"node_name": "worker-1"})

        self.assertTrue(payload["is_success"])
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["items"][0]["card_id"], "npu-a")
        self.assertEqual(payload["items"][0]["display_name"], "GPU 1")
        self.assertEqual(payload["items"][0]["memory_utilization_percent"], 12.5)
        self.assertEqual(payload["items"][1]["card_id"], "gpu-a")
        self.assertEqual(payload["items"][1]["display_name"], "GPU 2")
        self.assertEqual(payload["items"][1]["memory_utilization_percent"], 50.0)
        self.assertIsNone(payload["items"][1]["physical_gpu_allocated"])

    def test_memory_trend_preserves_real_time_positions_without_backfill(self):
        # The current single-card contract reads memory history from MySQL,
        # not the removed Prometheus gpu_utilization range-query endpoint.
        rows = [
            {"vendor": "nvidia", "card_id": "gpu-a", "bucket_no": 94, "utilization_avg": 5},
            {"vendor": "nvidia", "card_id": "gpu-a", "bucket_no": 95, "utilization_avg": 20},
        ]
        with patch.object(node_gpu, "load_accelerator_trend_buckets", return_value={"items": rows, "raw_sample_count": 2}) as load:
            payload = node_gpu.node_gpu_trend(
                "worker-1",
                "memory_utilization",
                "24h",
                {"node_name": "worker-1"},
                now_seconds=100000,
            )

        self.assertTrue(payload["is_success"])
        self.assertEqual(payload["start_timestamp"], (100000 - 86400) * 1000)
        self.assertEqual(payload["end_timestamp"], 100000 * 1000)
        self.assertEqual(payload["step_seconds"], 900)
        self.assertEqual(len(payload["series"][0]["points"]), 96)
        self.assertTrue(all(point[1] is None for point in payload["series"][0]["points"][:94]))
        self.assertEqual(payload["series"][0]["points"][-2:], [
            [(100000 - 1800) * 1000, 5.0],
            [(100000 - 900) * 1000, 20.0],
        ])
        self.assertEqual(load.call_args.args[-1], 900)

    def test_not_ready_node_is_rejected_before_prometheus_query(self):
        with patch.object(service, "nodes", return_value={
            "is_success": True,
            "items": [{"node_name": "worker-1", "status": "NotReady", "schedulable": False}],
        }):
            payload = service.node_gpus("worker-1", {})

        self.assertFalse(payload["is_success"])
        self.assertEqual(payload["http_status_code"], 409)

    def test_invalid_trend_metric_returns_clear_error(self):
        payload = node_gpu.node_gpu_trend(
            "worker-1",
            "vgpu_utilization",
            "1h",
            {"node_name": "worker-1"},
        )

        self.assertFalse(payload["is_success"])
        self.assertEqual(payload["http_status_code"], 400)


if __name__ == "__main__":
    unittest.main()
