"""Outbound webhook subscriptions, dispatch, retries, and API scopes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.audit.models import AuditLog
from app.api.models import ApiKey
from app.extensions import db
from app.webhooks.models import WebhookDelivery, WebhookSubscription
from app.webhooks.services import dispatch, retry_pending_deliveries


def _issue_key(*, organization_id: int, user_id: int, scopes: str) -> tuple[int, str]:
    key, raw = ApiKey.issue(
        name="Webhook scope test",
        organization_id=organization_id,
        user_id=user_id,
        scopes=scopes,
    )
    db.session.add(key)
    db.session.commit()
    return int(key.id), raw


def test_outbound_dispatch_signs_payload(app, organization, regular_user):
    calls = {}

    def fake_post(*, url: str, body_bytes: bytes, signature_hex: str, timeout_seconds: float):
        calls["url"] = url
        calls["body"] = body_bytes
        calls["sig"] = signature_hex
        return 200, "ok"

    with app.app_context():
        from app.webhooks.services import create_outbound_subscription

        sub, raw = create_outbound_subscription(
            organization_id=organization.id,
            url="https://example.com/hook",
            events=["invoice.paid"],
            created_by_user_id=regular_user.id,
        )
        delivery = dispatch(
            sub.id,
            "invoice.paid",
            {"invoice_id": 1},
            http_post=fake_post,
        )
        assert isinstance(delivery, WebhookDelivery)
        assert delivery.id is not None
        expected_sig = calls["sig"]
        assert len(expected_sig) == 64
        assert calls["url"] == "https://example.com/hook"
        raw_body = calls["body"]
        assert b'"invoice_id"' in raw_body


def test_outbound_retry_after_failure(app, organization, regular_user):
    with app.app_context():
        from app.webhooks.services import create_outbound_subscription

        sub, _raw = create_outbound_subscription(
            organization_id=organization.id,
            url="https://example.com/hook",
            events=["a.b"],
            created_by_user_id=regular_user.id,
        )

        def fail_post(**_kwargs):
            return None, "connection refused"

        dispatch(sub.id, "a.b", {"x": 1}, http_post=fail_post)
        sub = WebhookSubscription.query.get(sub.id)
        assert sub.failure_count >= 1
        d = WebhookDelivery.query.filter_by(subscription_id=sub.id).order_by(WebhookDelivery.id.desc()).first()
        assert d is not None
        assert d.next_retry_at is not None


def test_outbound_disabled_after_5_failures(app, organization, regular_user):
    with app.app_context():
        from app.webhooks.services import create_outbound_subscription

        sub, _raw = create_outbound_subscription(
            organization_id=organization.id,
            url="https://example.com/hook",
            events=["a.b"],
            created_by_user_id=regular_user.id,
        )

        def fail_post(**_kwargs):
            return 500, "err"

        for _ in range(5):
            dispatch(sub.id, "a.b", {"k": 1}, http_post=fail_post)

        sub = WebhookSubscription.query.get(sub.id)
        assert sub.is_active is False
        row = (
            AuditLog.query.filter_by(action="webhook.subscription_disabled")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert row is not None


def test_api_webhook_subscription_requires_scope(app, client, organization, regular_user):
    with app.app_context():
        key_id, raw = _issue_key(
            organization_id=organization.id,
            user_id=regular_user.id,
            scopes="reports:read",
        )
    rv = client.get(
        "/api/v1/webhooks/subscriptions",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert rv.status_code == 403

    with app.app_context():
        row = ApiKey.query.get(key_id)
        assert row is not None
        row.scopes = "reports:read,webhooks:read,webhooks:write"
        db.session.commit()

    rv2 = client.get(
        "/api/v1/webhooks/subscriptions",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert rv2.status_code == 200
    body = rv2.get_json()
    assert body["success"] is True


def test_outbound_subscription_tenant_isolation(app, client, organization, regular_user):
    from app.organizations.models import Organization
    from app.users.models import User, UserRole
    from werkzeug.security import generate_password_hash

    with app.app_context():
        org_b = Organization(name="Other Org B")
        db.session.add(org_b)
        db.session.flush()
        user_b = User(
            email="user-b@test.local",
            password_hash=generate_password_hash("UserPass123!"),
            organization_id=org_b.id,
            role=UserRole.USER.value,
            is_active=True,
        )
        db.session.add(user_b)
        db.session.commit()
        _key_b_id, raw_b = _issue_key(
            organization_id=org_b.id,
            user_id=user_b.id,
            scopes="webhooks:read,webhooks:write,reports:read",
        )
        from app.webhooks.services import create_outbound_subscription

        sub_b, _ = create_outbound_subscription(
            organization_id=org_b.id,
            url="https://b.example/hook",
            events=["e"],
            created_by_user_id=user_b.id,
        )
        sub_b_id = sub_b.id

    with app.app_context():
        _key_a_id, raw_a = _issue_key(
            organization_id=organization.id,
            user_id=regular_user.id,
            scopes="webhooks:read,webhooks:write,reports:read",
        )

    rv = client.delete(
        f"/api/v1/webhooks/subscriptions/{sub_b_id}",
        headers={"Authorization": f"Bearer {raw_a}"},
    )
    assert rv.status_code == 404

    rv_ok = client.delete(
        f"/api/v1/webhooks/subscriptions/{sub_b_id}",
        headers={"Authorization": f"Bearer {raw_b}"},
    )
    assert rv_ok.status_code == 200


def test_retry_pending_deliveries_marks_next(app, organization, regular_user):
    with app.app_context():
        from app.webhooks.services import create_outbound_subscription

        sub, _raw = create_outbound_subscription(
            organization_id=organization.id,
            url="https://example.com/hook",
            events=["retry.test"],
            created_by_user_id=regular_user.id,
        )

        def fail_post(**_kwargs):
            return None, "down"

        dispatch(sub.id, "retry.test", {"n": 1}, http_post=fail_post)
        d = WebhookDelivery.query.filter_by(subscription_id=sub.id).one()
        d.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.add(d)
        db.session.commit()

        def ok_post(**kwargs):
            _ = kwargs
            return 200, "ok"

        n = retry_pending_deliveries(http_post=ok_post)
        assert n >= 1
        d2 = WebhookDelivery.query.get(d.id)
        assert d2.delivered_at is not None


def test_webhook_services_metadata_helpers(app):
    with app.app_context():
        from app.webhooks.services import extract_event_metadata, provider_is_known, verify_signature

        assert provider_is_known("stripe") is True
        assert provider_is_known("paytrail") is True
        assert provider_is_known("nope") is False
        et, eid, org = extract_event_metadata("stripe", {"type": "checkout", "id": "evt_1", "organization_id": "1"})
        assert et == "checkout"
        assert eid == "evt_1"
        assert org == 1
        et2, eid2, org2 = extract_event_metadata("vismapay", {"event_type": "x", "order_number": "ord"})
        assert et2 == "x"
        assert eid2 == "ord"
        assert org2 is None
        assert verify_signature("unknown", b"{}", "sig", "secret") is False


def test_webhook_services_mark_processed_and_idempotency_helper(app):
    with app.app_context():
        from app.webhooks.services import apply_idempotency_for_inbound, mark_processed

        # no-op branch when event does not exist
        mark_processed(999999, None)
        sub = WebhookSubscription(
            organization_id=1,
            url="https://example.com/w",
            secret_hash="h",
            secret_encrypted="gAAAAABk",
            events=["x"],
            is_active=True,
            created_by_user_id=None,
        )
        db.session.add(sub)
        db.session.flush()
        delivery = WebhookDelivery(
            subscription_id=sub.id,
            event_type="x",
            payload={"a": 1},
            payload_hash="abc",
            signature="sig",
            attempt_number=1,
        )
        db.session.add(delivery)
        db.session.flush()
        from app.webhooks.models import WebhookEvent

        event = WebhookEvent(
            provider="pindora_lock",
            event_type="evt",
            external_id="evt-mark",
            payload={"ok": True},
            signature="s",
            signature_verified=True,
        )
        db.session.add(event)
        db.session.commit()
        mark_processed(event.id, "err")
        mark_processed(event.id, None)
        apply_idempotency_for_inbound(
            provider="pindora_lock",
            external_id="evt-mark",
            payload={"ok": True},
            organization_id=None,
        )
