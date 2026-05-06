from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.audit.models import AuditLog
from app.extensions import db
from app.webhooks.models import WebhookEvent
from app.webhooks.services import process_stale_inbound_webhook_events


def test_process_stale_inbound_webhook_marks_unprocessed_event(app):
    with app.app_context():
        created = datetime.now(timezone.utc) - timedelta(minutes=2)
        ev = WebhookEvent(
            provider="pindora_lock",
            event_type="test.event",
            external_id="inbound-stale-1",
            payload={"ok": True},
            signature="",
            signature_verified=True,
            processed=False,
            created_at=created,
        )
        db.session.add(ev)
        db.session.commit()
        eid = ev.id

        n = process_stale_inbound_webhook_events(min_age_seconds=30)
        assert n == 1

        row = WebhookEvent.query.get(eid)
        assert row is not None
        assert row.processed is True


def test_process_stale_inbound_webhook_dead_letter_after_max_attempts(app, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("handler down")

    monkeypatch.setattr("app.webhooks.services.dispatch_handler", boom)

    with app.app_context():
        created = datetime.now(timezone.utc) - timedelta(minutes=2)
        ev = WebhookEvent(
            provider="pindora_lock",
            event_type="test.event",
            external_id="inbound-dl-1",
            payload={},
            signature="",
            signature_verified=True,
            processed=False,
            inbound_handler_attempts=4,
            created_at=created,
        )
        db.session.add(ev)
        db.session.commit()
        eid = ev.id

        process_stale_inbound_webhook_events(min_age_seconds=30)

        row = WebhookEvent.query.get(eid)
        assert row is not None
        assert row.processed is True
        assert int(row.inbound_handler_attempts or 0) >= 5

        audit = AuditLog.query.filter_by(action="webhook.handler_dead_letter").first()
        assert audit is not None
