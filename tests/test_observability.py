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


def test_health_ready_returns_503_when_db_down(client, monkeypatch):
    from app.extensions import db

    def fail_execute(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(db.session, "execute", fail_execute)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
