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


def test_client_create_access_code_blocks_until_vendor_finalized():
    client = PindoraLockClient(base_url="https://lock.example", api_key="secret", timeout_seconds=7)
    try:
        client.create_access_code(
            provider_device_id="dev-1",
            code="123456",
            valid_from_iso="2026-04-28T10:00:00+00:00",
            valid_until_iso="2026-04-29T10:00:00+00:00",
        )
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "not yet finalized" in str(exc).lower()


def test_client_verifies_webhook_signature(app):
    webhook_signing_key = "test-only-lock-webhook-hmac-secret"
    app.config["PINDORA_LOCK_WEBHOOK_SECRET"] = webhook_signing_key
    payload = b'{"event":"code.revoked"}'
    digest = hmac.new(webhook_signing_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    client = PindoraLockClient(base_url="https://lock.example", api_key="secret")
    assert client.verify_webhook_signature(payload=payload, signature=digest) is True
    assert client.verify_webhook_signature(payload=payload, signature="bad") is False
