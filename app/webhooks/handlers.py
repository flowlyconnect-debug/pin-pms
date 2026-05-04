"""Provider-specific inbound webhook handlers (extend in later prompts)."""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.webhooks.models import WebhookEvent

logger = logging.getLogger(__name__)

HandlerFn = Callable[[WebhookEvent, dict[str, Any]], None]


def _noop_handler(event: WebhookEvent, payload: dict[str, Any]) -> None:
    _ = (event, payload)


def _pindora_lock_handler(event: WebhookEvent, payload: dict[str, Any]) -> None:
    """Placeholder: PMS reactions to lock events are wired in a follow-up change."""

    _ = (event, payload)


HANDLERS: dict[str, HandlerFn] = {
    "stripe": _noop_handler,
    "vismapay": _noop_handler,
    "pindora_lock": _pindora_lock_handler,
}


def dispatch_handler(*, provider: str, event: WebhookEvent, payload: dict[str, Any]) -> None:
    fn = HANDLERS.get(provider, _noop_handler)
    fn(event, payload)
