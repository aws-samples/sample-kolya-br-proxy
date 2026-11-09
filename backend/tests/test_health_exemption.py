"""Only the exact probe paths skip the security middleware."""

from fastapi.testclient import TestClient

from main import app

client = TestClient(app, raise_server_exceptions=False)


def test_probe_paths_still_reachable():
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/metrics").status_code == 200


def test_metrics_probe_omits_runtime_config():
    assert "observability" not in client.get("/health/metrics").json()


def test_lookalike_path_gets_security_headers():
    # Before: startswith("/health") let this skip header injection entirely.
    response = client.get("/healthz-anything")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
