"""Inbound webhook infrastructure tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from app.audit.models import AuditLog
from app.settings.models import Setting
from app.webhooks.models import WebhookEvent


def _hmac_hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_inbound_invalid_signature_returns_401(app, client):
    secret = "inbound-test-secret-please-change"
    with app.app_context():
        from app.webhooks.services import persist_inbound_webhook_secret

        persist_inbound_webhook_secret(
            provider="pindora_lock", plaintext=secret, actor_user_id=None
        )

    body = b'{"event":"x","id":"evt-1"}'
    rv = client.post(
        "/api/v1/webhooks/pindora_lock",
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": "not-a-valid-signature"},
    )
    assert rv.status_code == 401
    assert b"invalid" not in rv.data.lower()
    assert b"signature" not in rv.data.lower()

    with app.app_context():
        row = (
            AuditLog.query.filter_by(action="webhook.invalid_signature")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert row is not None


def test_inbound_unknown_provider_returns_404(client):
    rv = client.post(
        "/api/v1/webhooks/not-a-provider",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert rv.status_code == 404


def test_unknown_provider_returns_404_and_audits(app, client):
    rv = client.post(
        "/api/v1/webhooks/unknown-provider",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert rv.status_code == 404
    with app.app_context():
        row = (
            AuditLog.query.filter_by(action="webhook.unknown_provider")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert row is not None


def test_inbound_valid_signature_creates_event(app, client):
    secret = "inbound-valid-secret-abcdef"
    with app.app_context():
        from app.webhooks.services import persist_inbound_webhook_secret

        persist_inbound_webhook_secret(
            provider="pindora_lock", plaintext=secret, actor_user_id=None
        )

    body_dict = {"event": "code.created", "id": "evt-valid-1"}
    body = json.dumps(body_dict).encode("utf-8")
    sig = _hmac_hex(secret, body)
    rv = client.post(
        "/api/v1/webhooks/pindora_lock",
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": sig},
    )
    assert rv.status_code == 200

    with app.app_context():
        ev = WebhookEvent.query.filter_by(provider="pindora_lock", external_id="evt-valid-1").one()
        assert ev.signature_verified is True


def test_inbound_duplicate_external_id_is_idempotent(app, client):
    secret = "inbound-dup-secret-ghijkl"
    with app.app_context():
        from app.webhooks.services import persist_inbound_webhook_secret

        persist_inbound_webhook_secret(
            provider="pindora_lock", plaintext=secret, actor_user_id=None
        )

    body_dict = {"event": "lock.event", "id": "evt-dup-1"}
    body = json.dumps(body_dict).encode("utf-8")
    sig = _hmac_hex(secret, body)
    rv1 = client.post(
        "/api/v1/webhooks/pindora_lock",
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": sig},
    )
    rv2 = client.post(
        "/api/v1/webhooks/pindora_lock",
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": sig},
    )
    assert rv1.status_code == 200
    assert rv2.status_code == 200
    with app.app_context():
        assert (
            WebhookEvent.query.filter_by(provider="pindora_lock", external_id="evt-dup-1").count()
            == 1
        )
        dup = (
            AuditLog.query.filter_by(action="webhook.duplicate_ignored")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert dup is not None


def test_payload_too_large_returns_413_and_audits(app, client):
    big = b"a" * (1024 * 1024 + 1)
    rv = client.post(
        "/api/v1/webhooks/stripe",
        data=big,
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": "x",
            "Content-Length": str(len(big)),
        },
    )
    assert rv.status_code == 413
    with app.app_context():
        row = (
            AuditLog.query.filter_by(action="webhook.payload_too_large")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert row is not None


def test_webhook_processing_deferred_when_slow(app, client, monkeypatch):
    secret = "slow-secret"
    with app.app_context():
        from app.webhooks.services import persist_inbound_webhook_secret

        persist_inbound_webhook_secret(
            provider="pindora_lock", plaintext=secret, actor_user_id=None
        )
    payload = {"event": "slow.event", "id": "evt-slow-1"}
    body = json.dumps(payload).encode("utf-8")
    sig = _hmac_hex(secret, body)

    def slow_handler(*, provider, event, payload):
        _ = (provider, event, payload)
        time.sleep(5.1)

    monkeypatch.setattr("app.webhooks.routes.dispatch_handler", slow_handler)
    rv = client.post(
        "/api/v1/webhooks/pindora_lock",
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": sig},
    )
    assert rv.status_code == 200
    with app.app_context():
        row = WebhookEvent.query.filter_by(external_id="evt-slow-1").first()
        assert row is not None
        assert row.processed is False


def test_webhook_missing_secret_returns_401_and_audits(app, client):
    _ = app
    rv = client.post(
        "/api/v1/webhooks/vismapay",
        data=b"{}",
        headers={"Content-Type": "application/json", "X-VismaPay-Signature": "x"},
    )
    assert rv.status_code == 401
    with app.app_context():
        row = (
            AuditLog.query.filter_by(action="webhook.invalid_signature")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert row is not None


def test_webhook_invalid_json_returns_400(app, client):
    secret = "invalid-json-secret"
    with app.app_context():
        from app.webhooks.services import persist_inbound_webhook_secret

        persist_inbound_webhook_secret(
            provider="pindora_lock", plaintext=secret, actor_user_id=None
        )
    body = b"{not-json"
    sig = _hmac_hex(secret, body)
    rv = client.post(
        "/api/v1/webhooks/pindora_lock",
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": sig},
    )
    assert rv.status_code == 400


def test_webhook_idempotency_conflict_returns_409(app, client, monkeypatch):
    secret = "idem-conflict-secret"
    with app.app_context():
        from app.webhooks.services import persist_inbound_webhook_secret

        persist_inbound_webhook_secret(
            provider="pindora_lock", plaintext=secret, actor_user_id=None
        )
    body = b'{"event":"x","id":"evt-conflict"}'
    sig = _hmac_hex(secret, body)

    from app.idempotency.services import IdempotencyKeyConflict

    def raise_conflict(**_kwargs):
        raise IdempotencyKeyConflict()

    monkeypatch.setattr("app.webhooks.routes.apply_idempotency_for_inbound", raise_conflict)
    rv = client.post(
        "/api/v1/webhooks/pindora_lock",
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": sig},
    )
    assert rv.status_code == 409


def test_stripe_webhook_valid_signature_returns_200(app, client, monkeypatch):
    monkeypatch.setattr(
        "app.payments.providers.stripe.StripeProvider.verify_webhook", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        "app.payments.providers.stripe.StripeProvider.parse_webhook_event",
        lambda *args, **kwargs: {"type": "unknown"},
    )
    rv = client.post(
        "/api/v1/webhooks/stripe",
        data=b'{"type":"x","data":{"object":{}}}',
        headers={"Content-Type": "application/json", "Stripe-Signature": "ok"},
    )
    assert rv.status_code == 200


def test_audit_log_for_received_processed_invalid_signature(app, client):
    secret = "audit-secret-zzzz"
    with app.app_context():
        from app.webhooks.services import persist_inbound_webhook_secret

        persist_inbound_webhook_secret(
            provider="pindora_lock", plaintext=secret, actor_user_id=None
        )

    body = b'{"event":"e","id":"evt-audit-1"}'
    client.post(
        "/api/v1/webhooks/pindora_lock",
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": "bad"},
    )
    client.post(
        "/api/v1/webhooks/pindora_lock",
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": _hmac_hex(secret, body)},
    )

    with app.app_context():
        actions = {r.action for r in AuditLog.query.all()}
        assert "webhook.invalid_signature" in actions
        assert "webhook.received" in actions
        assert "webhook.processed" in actions


def test_secret_is_not_stored_plaintext(app):
    plain = "unique_plain_secret_value_xyz_123"
    with app.app_context():
        from app.webhooks.services import persist_inbound_webhook_secret

        persist_inbound_webhook_secret(provider="stripe", plaintext=plain, actor_user_id=None)
        row = Setting.query.filter_by(key="webhooks.stripe.secret").one()
        assert plain not in (row.value or "")
        assert (row.value or "").startswith("gAAAAA")


@pytest.mark.no_db_isolation
def test_secret_is_not_in_logs():
    from app.core.logging import redact

    sensitive = "super_secret_token_value_999"
    out = redact(f"signature={sensitive} ok")
    assert sensitive not in out


def test_pindora_lock_webhook_still_works(app, client):
    """Regression: same HMAC semantics as PindoraLockClient.verify_webhook_signature."""

    secret = "test-only-lock-webhook-hmac-secret"
    app.config["PINDORA_LOCK_WEBHOOK_SECRET"] = secret
    payload = b'{"event":"code.revoked","id":"evt-lock-reg"}'
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    rv = client.post(
        "/api/v1/webhooks/pindora_lock",
        data=payload,
        headers={"Content-Type": "application/json", "X-Signature": digest},
    )
    assert rv.status_code == 200
    with app.app_context():
        assert WebhookEvent.query.filter_by(external_id="evt-lock-reg").count() == 1


def test_pindora_lock_client_verify_webhook_signature(app):
    from app.integrations.pindora_lock.client import PindoraLockClient

    webhook_signing_key = "test-only-lock-webhook-hmac-secret"
    app.config["PINDORA_LOCK_WEBHOOK_SECRET"] = webhook_signing_key
    payload = b'{"event":"code.revoked"}'
    digest = hmac.new(webhook_signing_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    client = PindoraLockClient(base_url="https://lock.example", api_key="secret")
    with app.app_context():
        assert client.verify_webhook_signature(payload=payload, signature=digest) is True
        assert client.verify_webhook_signature(payload=payload, signature="bad") is False
