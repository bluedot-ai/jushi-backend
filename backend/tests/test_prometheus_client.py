import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.services.prometheus_client import PrometheusClient


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class PrometheusClientTests(unittest.TestCase):
    def test_missing_base_url_is_reported_without_request(self):
        rows, error = PrometheusClient("").query("up")

        self.assertIsNone(rows)
        self.assertEqual(error, "PROMETHEUS_BASE_URL is not configured")

    def test_query_passes_auth_query_and_timeout(self):
        calls = []

        def get(url, **kwargs):
            calls.append((url, kwargs))
            return _Response({
                "status": "success",
                "data": {"result": [{"metric": {"node": "worker-1"}, "value": [0, "1"]}]},
            })

        fake_requests = SimpleNamespace(
            get=get,
            Timeout=TimeoutError,
            RequestException=OSError,
        )
        with patch.dict(sys.modules, {"requests": fake_requests}):
            rows, error = PrometheusClient(
                "https://prometheus.example/",
                token="test-token",
                timeout_seconds=7,
            ).query("up")

        self.assertIsNone(error)
        self.assertEqual(rows[0]["metric"]["node"], "worker-1")
        self.assertEqual(calls[0][0], "https://prometheus.example/api/v1/query")
        self.assertEqual(calls[0][1]["params"], {"query": "up"})
        self.assertEqual(calls[0][1]["headers"], {"Authorization": "Bearer test-token"})
        self.assertEqual(calls[0][1]["timeout"], 7)

    def test_prometheus_error_payload_is_preserved(self):
        fake_requests = SimpleNamespace(
            get=lambda *_args, **_kwargs: _Response({"status": "error", "error": "bad query"}),
            Timeout=TimeoutError,
            RequestException=OSError,
        )
        with patch.dict(sys.modules, {"requests": fake_requests}):
            rows, error = PrometheusClient("https://prometheus.example").query("bad")

        self.assertIsNone(rows)
        self.assertEqual(error, "bad query")

    def test_query_range_passes_time_window_and_step(self):
        calls = []

        def get(url, **kwargs):
            calls.append((url, kwargs))
            return _Response({
                "status": "success",
                "data": {"resultType": "matrix", "result": []},
            })

        fake_requests = SimpleNamespace(get=get)
        with patch.dict(sys.modules, {"requests": fake_requests}):
            rows, error = PrometheusClient("https://prometheus.example").query_range(
                "up",
                100,
                200,
                30,
            )

        self.assertIsNone(error)
        self.assertEqual(rows, [])
        self.assertEqual(calls[0][0], "https://prometheus.example/api/v1/query_range")
        self.assertEqual(calls[0][1]["params"], {
            "query": "up",
            "start": 100,
            "end": 200,
            "step": 30,
        })


if __name__ == "__main__":
    unittest.main()

