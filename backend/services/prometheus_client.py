"""Small reusable client for Prometheus instant and range queries."""


class PrometheusClient:
    def __init__(self, base_url: str, token: str = "", timeout_seconds: int = 5):
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_config(cls, config):
        return cls(
            getattr(config, "PROMETHEUS_BASE_URL", ""),
            getattr(config, "PROMETHEUS_TOKEN", ""),
            getattr(config, "PROMETHEUS_TIMEOUT_SECONDS", 5),
        )

    def query(self, promql: str):
        return self._request("/api/v1/query", {"query": promql})

    def query_range(self, promql: str, start, end, step):
        """Run a Prometheus range query and return the matrix rows."""
        return self._request(
            "/api/v1/query_range",
            {
                "query": promql,
                "start": start,
                "end": end,
                "step": step,
            },
        )

    def _request(self, path: str, params: dict):
        if not self.base_url:
            return None, "PROMETHEUS_BASE_URL is not configured"

        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        try:
            import requests

            response = requests.get(
                f"{self.base_url}{path}",
                params=params,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            # Preserve the resources API's existing best-effort diagnostics:
            # metric failures must not make the resource page crash.
            return None, str(exc)

        if payload.get("status") != "success":
            return None, payload.get("error") or "Prometheus query failed"

        result = ((payload.get("data") or {}).get("result") or [])
        return result if isinstance(result, list) else [], None

