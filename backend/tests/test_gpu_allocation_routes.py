"""HTTP/auth contracts; no collectors, live clusters or databases are started."""

import unittest
from datetime import datetime
from unittest.mock import patch

with patch.dict("os.environ", {
    "RESOURCE_AUTO_SNAPSHOT_ENABLED": "false",
    "RESOURCE_TREND_CACHE_ENABLED": "false",
    "ACCELERATOR_HISTORY_ENABLED": "false",
    "GPU_ALLOCATION_HISTORY_ENABLED": "false",
}):
    from backend import app as app_module

from backend.common.auth import create_token
from backend.modules.docs.openapi_specs import build_openapi_spec
from backend.modules.resources import gpu_allocation_routes as routes


class GpuAllocationRouteTests(unittest.TestCase):
    def setUp(self):
        self.user = {"id": 42, "username": "test-reader", "role": "user", "status": "active"}
        self.auth = patch.object(app_module, "find_auth_user_by_id", side_effect=lambda _: self.user)
        self.auth.start()
        self.addCleanup(self.auth.stop)
        with (
            patch.object(app_module, "start_resource_snapshot_collector", return_value=False),
            patch.object(app_module, "start_resource_trend_cache_refresher", return_value=False),
            patch.object(app_module, "start_accelerator_metric_collector", return_value=False),
            patch.object(app_module, "start_gpu_allocation_collector", return_value=False),
        ):
            self.client = app_module.create_app().test_client()
        self.headers = {"Authorization": "Bearer " + create_token(self.user)}

    def test_all_four_new_endpoints_require_login(self):
        with patch.object(routes.gpu_allocation_collector, "collect_and_save_once") as collect:
            for path in ("current", "trend", "compare"):
                response = self.client.get("/api/resources/gpu-allocation/" + path)
                self.assertEqual(response.status_code, 401)
            response = self.client.post("/api/internal/gpu-allocation/collect")
            self.assertEqual(response.status_code, 401)
            collect.assert_not_called()

    def test_non_admin_cannot_trigger_collection(self):
        with patch.object(routes.gpu_allocation_collector, "collect_and_save_once") as collect:
            response = self.client.post("/api/internal/gpu-allocation/collect", headers=self.headers)
        self.assertEqual(response.status_code, 403)
        collect.assert_not_called()

    def test_current_query_does_not_write(self):
        snapshot = {"sampled_at": datetime(2026, 10, 10, 14, 30), "gpu_capacity": 7,
                    "allocation_rate": None, "gpu_utilization_avg": None}
        with (
            patch.object(routes.gpu_allocation_collector, "build_current_snapshot", return_value=(snapshot, {"allocation_issues": []})),
            patch.object(routes.gpu_allocation_collector, "collect_and_save_once") as collect,
        ):
            response = self.client.get("/api/resources/gpu-allocation/current", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["sampled_at"], "2026-10-10T14:30:00+08:00")
        self.assertIsNone(data["allocation_rate"])
        collect.assert_not_called()

    def test_current_can_select_ascend_without_switching_cluster_or_writing(self):
        snapshot = {"vendor": "ascend", "gpu_capacity": 2, "allocation_valid": True}
        with patch.object(routes.gpu_allocation_collector, "build_current_snapshot", return_value=(snapshot, {})) as current:
            response = self.client.get("/api/resources/gpu-allocation/current?vendor=ascend", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["vendor"], "ascend")
        current.assert_called_once_with(vendor="ascend", include_observations=True)

    def test_current_invalid_vendor_does_not_contact_data_source(self):
        with patch.object(routes.gpu_allocation_collector, "build_current_snapshot") as current:
            response = self.client.get("/api/resources/gpu-allocation/current?vendor=unknown", headers=self.headers)
        self.assertEqual(response.status_code, 400)
        current.assert_not_called()

    def test_admin_collection_ignores_supplied_metrics_and_time(self):
        self.user["role"] = "admin"
        with patch.object(routes.gpu_allocation_collector, "collect_and_save_once", return_value={"saved": True, "save_error": None}) as collect:
            response = self.client.post("/api/internal/gpu-allocation/collect", headers=self.headers,
                                        json={"gpu_allocated": 999, "sampled_at": "2020-01-01", "cluster_name": "foreign"})
        self.assertEqual(response.status_code, 200)
        collect.assert_called_once_with()

    def test_write_errors_return_real_http_status_without_sensitive_error(self):
        self.user["role"] = "admin"
        with patch.object(routes.gpu_allocation_collector, "collect_and_save_once", return_value={"save_error": "secret DB connection details"}):
            response = self.client.post("/api/internal/gpu-allocation/collect", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", response.get_data(as_text=True))

    def test_invalid_query_is_http_400_not_success_200(self):
        response = self.client.get("/api/resources/gpu-allocation/trend?start=bad&end=bad", headers=self.headers)
        self.assertEqual(response.status_code, 400)
        response = self.client.get("/api/resources/gpu-allocation/compare?base_month=bad&compare_month=bad", headers=self.headers)
        self.assertEqual(response.status_code, 400)

    def test_expired_or_invalid_token_rejected(self):
        response = self.client.get("/api/resources/gpu-allocation/current", headers={"Authorization": "Bearer invalid"})
        self.assertEqual(response.status_code, 401)

    def test_openapi_contains_new_paths_without_auth_exemption(self):
        spec = build_openapi_spec()
        paths = ("/api/resources/gpu-allocation/current", "/api/resources/gpu-allocation/trend",
                 "/api/resources/gpu-allocation/compare", "/api/internal/gpu-allocation/collect")
        for path in paths:
            self.assertIn(path, spec["paths"])
            self.assertFalse(app_module._is_auth_exempt(path))
        self.assertIn("403", spec["paths"][paths[-1]]["post"]["responses"])


if __name__ == "__main__":
    unittest.main()
