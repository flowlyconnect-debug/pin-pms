from __future__ import annotations

from app.webhooks.handlers import dispatch_handler
from app.webhooks.models import WebhookEvent


def test_dispatch_handler_covers_unknown_and_pindora_paths():
    event = WebhookEvent(provider="pindora_lock", event_type="x", external_id="evt-1", payload={})
    dispatch_handler(provider="unknown_provider", event=event, payload={})
    dispatch_handler(provider="pindora_lock", event=event, payload={"event": "lock.changed"})

