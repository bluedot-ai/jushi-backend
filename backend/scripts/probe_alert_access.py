import json
import os
import ssl
import sys
import urllib.error
import urllib.request


def _request_json(base_url: str, token: str, path: str) -> tuple[int | None, dict]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, timeout=15, context=context) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body[:500]}
        return exc.code, payload


def _print_probe(name: str, status: int | None, payload: dict) -> None:
    print(f"{name}_http={status}")
    items = payload.get("items")
    if isinstance(items, list):
        print(f"{name}_count={len(items)}")
        for item in items[:5]:
            metadata = item.get("metadata") or {}
            status_info = item.get("status") or {}
            print(f"{name}_item={metadata.get('name')} {status_info.get('phase') or item.get('reason') or ''}")
        return
    print(f"{name}_error={payload}")


def main() -> int:
    base_url = os.getenv("K8S_API_BASE", "").strip()
    token = os.getenv("K8S_TOKEN", "").strip().strip('"') or os.getenv("DCE_TOKEN", "").strip().strip('"')
    namespace = os.getenv("DCE_NAMESPACE", "algorithm").strip() or "algorithm"
    scope = os.getenv("ALERT_SCOPE", "cluster").strip() or "cluster"

    if not base_url:
        print("K8S_API_BASE is required")
        return 2
    if not token:
        print("K8S_TOKEN or DCE_TOKEN is required")
        return 2

    paths = [
        ("pods", "/api/v1/pods" if scope == "cluster" else f"/api/v1/namespaces/{namespace}/pods"),
        ("events", "/api/v1/events" if scope == "cluster" else f"/api/v1/namespaces/{namespace}/events"),
        ("nodes", "/api/v1/nodes"),
    ]
    for name, path in paths:
        try:
            status, payload = _request_json(base_url, token, path)
        except Exception as exc:
            print(f"{name}_exception={type(exc).__name__}: {exc}")
            continue
        _print_probe(name, status, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
