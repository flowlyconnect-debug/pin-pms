from __future__ import annotations

from datetime import date
from unittest.mock import Mock

from app.audit.models import AuditLog
from app.extensions import db
from app.guests.models import Guest
from app.organizations.models import Organization
from app.properties.models import Property, Unit
from app.webhooks.events import RESERVATION_CREATED
from app.webhooks.models import WebhookSubscription
from app.webhooks.publisher import publish
from app.webhooks.schemas import build_reservation_created_payload


def _mk_property_unit(*, organization_id: int) -> Unit:
    prop = Property(organization_id=organization_id, name="P1", address="A1")
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="U1", unit_type="studio")
    db.session.add(unit)
    db.session.flush()
    return unit


def _mk_guest(*, organization_id: int, email: str = "guest@example.test") -> Guest:
    guest = Guest(
        organization_id=organization_id,
        first_name="Test",
        last_name="Guest",
        email=email,
    )
    db.session.add(guest)
    db.session.flush()
    return guest


def _mk_subscription(
    *,
    organization_id: int,
    event_types: list[str],
    is_active: bool = True,
) -> WebhookSubscription:
    row = WebhookSubscription(
        organization_id=organization_id,
        url="https://example.test/hook",
        secret_hash="x" * 64,
        secret_encrypted="gAAAAABx-test-encrypted-secret",
        events=event_types,
        is_active=is_active,
    )
    db.session.add(row)
    db.session.commit()
    return row


def test_reservation_created_publishes_to_matching_subscriptions(app, organization, monkeypatch):
    from app.reservations import services as reservation_services

    with app.app_context():
        unit = _mk_property_unit(organization_id=organization.id)
        guest = _mk_guest(organization_id=organization.id)
        sub = _mk_subscription(organization_id=organization.id, event_types=[RESERVATION_CREATED])
        called = []

        def fake_dispatch(subscription_id, event_type, payload):
            called.append((subscription_id, event_type, payload))
            return None

        monkeypatch.setattr("app.webhooks.publisher.dispatch", fake_dispatch)
        row = reservation_services.create_reservation(
            organization_id=organization.id,
            unit_id=unit.id,
            guest_id=guest.id,
            start_date_raw="2026-06-01",
            end_date_raw="2026-06-03",
            actor_user_id=None,
        )
        assert row["id"] is not None
        assert len(called) == 1
        assert called[0][0] == sub.id
        assert called[0][1] == RESERVATION_CREATED
        assert called[0][2]["event"] == RESERVATION_CREATED


def test_subscription_with_no_matching_events_not_called(app, organization, monkeypatch):
    with app.app_context():
        _mk_subscription(organization_id=organization.id, event_types=["invoice.created"])
        fake_dispatch = Mock()
        monkeypatch.setattr("app.webhooks.publisher.dispatch", fake_dispatch)
        publish(RESERVATION_CREATED, organization.id, {"event": RESERVATION_CREATED, "data": {}})
        fake_dispatch.assert_not_called()


def test_subscription_in_other_org_not_called(app, organization, monkeypatch):
    with app.app_context():
        org_b = Organization(name="Org B")
        db.session.add(org_b)
        db.session.commit()
        _mk_subscription(organization_id=org_b.id, event_types=[RESERVATION_CREATED])
        fake_dispatch = Mock()
        monkeypatch.setattr("app.webhooks.publisher.dispatch", fake_dispatch)
        publish(RESERVATION_CREATED, organization.id, {"event": RESERVATION_CREATED, "data": {}})
        fake_dispatch.assert_not_called()


def test_publish_handles_dispatch_failure_gracefully(app, organization, monkeypatch):
    with app.app_context():
        sub1 = _mk_subscription(organization_id=organization.id, event_types=[RESERVATION_CREATED])
        sub2 = _mk_subscription(organization_id=organization.id, event_types=[RESERVATION_CREATED])
        called = []

        def flaky_dispatch(subscription_id, event_type, payload):
            called.append(subscription_id)
            if subscription_id == sub1.id:
                raise RuntimeError("boom")
            return None

        monkeypatch.setattr("app.webhooks.publisher.dispatch", flaky_dispatch)
        publish(RESERVATION_CREATED, organization.id, {"event": RESERVATION_CREATED, "data": {}})
        assert sub1.id in called
        assert sub2.id in called


def test_publish_does_not_block_request_when_async(app, organization, monkeypatch):
    with app.app_context():
        _mk_subscription(organization_id=organization.id, event_types=[RESERVATION_CREATED])
        app.config["WEBHOOK_PUBLISH_ASYNC"] = True
        fake_dispatch = Mock()
        submit_calls = []

        def fake_submit(fn, **kwargs):
            submit_calls.append((fn, kwargs))
            return Mock()

        monkeypatch.setattr("app.webhooks.publisher.dispatch", fake_dispatch)
        monkeypatch.setattr("app.webhooks.publisher._EXECUTOR.submit", fake_submit)
        publish(RESERVATION_CREATED, organization.id, {"event": RESERVATION_CREATED, "data": {}})
        fake_dispatch.assert_not_called()
        assert len(submit_calls) == 1


def test_payload_does_not_leak_pii(app, organization):
    from app.reservations.models import Reservation

    with app.app_context():
        unit = _mk_property_unit(organization_id=organization.id)
        guest = _mk_guest(organization_id=organization.id, email="pii@example.test")
        row = Reservation(
            unit_id=unit.id,
            guest_id=guest.id,
            guest_name="Guest",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 3),
            status="confirmed",
            payment_status="pending",
            currency="EUR",
        )
        db.session.add(row)
        db.session.commit()
        payload = build_reservation_created_payload(row)
        payload_text = str(payload)
        assert guest.email not in payload_text
        assert payload["data"]["guest_id"] == guest.id
        assert "guest_email" not in payload["data"]


def test_audit_log_for_webhook_published(app, organization, monkeypatch):
    with app.app_context():
        _mk_subscription(organization_id=organization.id, event_types=[RESERVATION_CREATED])
        monkeypatch.setattr("app.webhooks.publisher.dispatch", lambda *_args, **_kwargs: None)
        publish(RESERVATION_CREATED, organization.id, {"event": RESERVATION_CREATED, "data": {}})
        row = (
            AuditLog.query.filter_by(action="webhook.published")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert row is not None
        assert row.context["event_type"] == RESERVATION_CREATED
        assert row.context["subscriber_count"] == 1


def test_inactive_subscription_not_called(app, organization, monkeypatch):
    with app.app_context():
        _mk_subscription(
            organization_id=organization.id,
            event_types=[RESERVATION_CREATED],
            is_active=False,
        )
        fake_dispatch = Mock()
        monkeypatch.setattr("app.webhooks.publisher.dispatch", fake_dispatch)
        publish(RESERVATION_CREATED, organization.id, {"event": RESERVATION_CREATED, "data": {}})
        fake_dispatch.assert_not_called()


def test_publish_after_commit_only(app, organization, monkeypatch):
    from app.reservations import services as reservation_services

    with app.app_context():
        unit = _mk_property_unit(organization_id=organization.id)
        guest = _mk_guest(organization_id=organization.id)
        _mk_subscription(organization_id=organization.id, event_types=[RESERVATION_CREATED])
        publish_calls = []

        def fake_publish(*args, **kwargs):
            publish_calls.append((args, kwargs))

        monkeypatch.setattr(reservation_services, "publish_webhook_event", fake_publish)
        reservation_services.create_reservation(
            organization_id=organization.id,
            unit_id=unit.id,
            guest_id=guest.id,
            start_date_raw="2026-06-01",
            end_date_raw="2026-06-03",
            actor_user_id=None,
        )
        assert len(publish_calls) == 1

        # Overlap triggers validation before commit; no publish should happen.
        try:
            reservation_services.create_reservation(
                organization_id=organization.id,
                unit_id=unit.id,
                guest_id=guest.id,
                start_date_raw="2026-06-02",
                end_date_raw="2026-06-04",
                actor_user_id=None,
            )
        except reservation_services.ReservationServiceError:
            pass
        assert len(publish_calls) == 1
