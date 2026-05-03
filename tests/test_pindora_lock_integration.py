from __future__ import annotations

import hashlib
import hmac

from app.integrations.pindora_lock import adapter
from app.integrations.pindora_lock.client import PindoraLockClient


def test_adapter_normalizes_code_payload():
    payload = {"id": "abc-123", "status": "CREATED"}
    out = adapter.normalize_code_create(payload)
    assert out["provider_code_id"] == "abc-123"
    assert out["status"] == "created"


def test_client_create_access_code_uses_requests(monkeypatch):
    calls = {}

    class FakeResponse:
        status_code = 200
        content = b'{"id":"provider-code-1","status":"created"}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "provider-code-1", "status": "created"}

    def fake_request(method, url, headers, json, timeout):  # noqa: A002
        calls["method"] = method
        calls["url"] = url
        calls["json"] = json
        calls["headers"] = headers
        calls["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.integrations.pindora_lock.client.requests.request", fake_request)
    client = PindoraLockClient(base_url="https://lock.example", api_key="secret", timeout_seconds=7)
    body = client.create_access_code(
        provider_device_id="dev-1",
        code="123456",
        valid_from_iso="2026-04-28T10:00:00+00:00",
        valid_until_iso="2026-04-29T10:00:00+00:00",
    )
    assert calls["method"] == "POST"
    assert calls["url"].endswith("/devices/dev-1/codes")
    assert calls["json"]["code"] == "123456"
    assert calls["headers"]["Authorization"] == "Bearer secret"
    assert body["id"] == "provider-code-1"


def test_client_verifies_webhook_signature(app):
    webhook_signing_key = "test-only-lock-webhook-hmac-secret"
    app.config["PINDORA_LOCK_WEBHOOK_SECRET"] = webhook_signing_key
    payload = b'{"event":"code.revoked"}'
    digest = hmac.new(webhook_signing_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    client = PindoraLockClient(base_url="https://lock.example", api_key="secret")
    assert client.verify_webhook_signature(payload=payload, signature=digest) is True
    assert client.verify_webhook_signature(payload=payload, signature="bad") is False
