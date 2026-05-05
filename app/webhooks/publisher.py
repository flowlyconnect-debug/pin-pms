"""Business-event publisher for outbound webhook subscriptions."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from flask import current_app

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.extensions import db
from app.webhooks.models import WebhookSubscription
from app.webhooks.services import dispatch

logger = logging.getLogger(__name__)

_SYNC_MAX_SUBSCRIBERS = 3
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="webhook-publisher")


def _matching_subscription_ids(*, organization_id: int, event_type: str) -> list[int]:
    rows = (
        WebhookSubscription.query.filter_by(organization_id=organization_id, is_active=True)
        .order_by(WebhookSubscription.id.asc())
        .all()
    )
    out: list[int] = []
    for row in rows:
        events = row.events if isinstance(row.events, list) else []
        if event_type in events:
            out.append(int(row.id))
    return out


def _dispatch_one(*, subscription_id: int, event_type: str, payload: dict) -> None:
    try:
        dispatch(subscription_id, event_type, payload)
    except Exception:
        logger.exception(
            "Outbound webhook dispatch failed: subscription_id=%s event_type=%s",
            subscription_id,
            event_type,
        )


def _dispatch_many_background(*, app_obj, subscription_ids: list[int], event_type: str, payload: dict) -> None:
    with app_obj.app_context():
        for subscription_id in subscription_ids:
            _dispatch_one(subscription_id=subscription_id, event_type=event_type, payload=payload)
        db.session.remove()


def publish(event_type: str, organization_id: int, payload: dict) -> None:
    """Publish one business event to active, tenant-scoped subscribers."""

    subscription_ids = _matching_subscription_ids(
        organization_id=organization_id,
        event_type=event_type,
    )
    if not subscription_ids:
        audit_record(
            "webhook.published",
            status=AuditStatus.SUCCESS,
            organization_id=organization_id,
            target_type="webhook_event",
            target_id=None,
            metadata={
                "event_type": event_type,
                "organization_id": organization_id,
                "subscriber_count": 0,
            },
            commit=True,
        )
        return

    async_mode = bool(current_app.config.get("WEBHOOK_PUBLISH_ASYNC", False))
    head = subscription_ids[:_SYNC_MAX_SUBSCRIBERS]
    tail = subscription_ids[_SYNC_MAX_SUBSCRIBERS:]

    if async_mode:
        app_obj = current_app._get_current_object()
        _EXECUTOR.submit(
            _dispatch_many_background,
            app_obj=app_obj,
            subscription_ids=list(subscription_ids),
            event_type=event_type,
            payload=payload,
        )
    else:
        for subscription_id in head:
            _dispatch_one(subscription_id=subscription_id, event_type=event_type, payload=payload)
        if tail:
            app_obj = current_app._get_current_object()
            _EXECUTOR.submit(
                _dispatch_many_background,
                app_obj=app_obj,
                subscription_ids=list(tail),
                event_type=event_type,
                payload=payload,
            )

    audit_record(
        "webhook.published",
        status=AuditStatus.SUCCESS,
        organization_id=organization_id,
        target_type="webhook_event",
        target_id=None,
        metadata={
            "event_type": event_type,
            "organization_id": organization_id,
            "subscriber_count": len(subscription_ids),
        },
        commit=True,
    )
