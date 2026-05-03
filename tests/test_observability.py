from __future__ import annotations


def test_request_id_header_and_log_context(app, client):
    from app.core.logging import _attach_request_context

    with app.test_request_context("/health"):
        app.preprocess_request()
        payload = _attach_request_context(None, "info", {})
        assert payload["request_id"] is not None

    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers.get("X-Request-Id")


def test_health_ready_returns_503_when_not_ready(client, api_key, monkeypatch):
    """Readiness uses ``readiness_status``; patch it so checks fail without breaking API-key lookup."""

    monkeypatch.setattr(
        "app.api.routes.readiness_status",
        lambda _app: {"ok": False, "checks": {"db": {"ok": False, "detail": "synthetic"}}},
    )
    response = client.get(
        "/api/v1/health/ready",
        headers={"Authorization": f"Bearer {api_key.raw}"},
    )
    assert response.status_code == 503
