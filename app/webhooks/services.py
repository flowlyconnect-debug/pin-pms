"""Webhook service layer — inbound verification, persistence, outbound dispatch."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.extensions import db
from app.idempotency.services import get_or_create
from app.settings import services as settings_service
from app.settings.models import SettingType
from app.webhooks.crypto import decrypt_signing_secret, encrypt_signing_secret
from app.webhooks.handlers import dispatch_handler
from app.webhooks.models import WebhookDelivery, WebhookEvent, WebhookSubscription
from app.webhooks.signature import hmac_sha256_hex_digest, verify_hmac_sha256_hex

logger = logging.getLogger(__name__)

_BACKOFF_SECONDS = (60, 300, 1800, 7200, 43200)
_RESPONSE_BODY_MAX = 8 * 1024
_ERROR_AUDIT_MAX = 512

_INBOUND_SETTING_KEY = {
    "stripe": "webhooks.stripe.secret",
    "paytrail": "webhooks.paytrail.secret",
    "vismapay": "webhooks.vismapay.secret",
    "pindora_lock": "webhooks.pindora_lock.secret",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _truncate(text: str | None, max_len: int) -> str | None:
    if text is None:
        return None
    if len(text) <= max_len:
        return text
    return text[:max_len]


def verify_signature(
    provider: str,
    payload_bytes: bytes,
    signature_header: str,
    secret: str,
) -> bool:
    """Verify inbound webhook authenticity (HMAC-SHA256; Stripe ``v1=`` hex supported)."""

    if provider in ("pindora_lock", "vismapay", "stripe"):
        return verify_hmac_sha256_hex(
            secret=secret,
            payload_bytes=payload_bytes,
            signature_header=signature_header,
        )
    return False


def _decrypt_if_encrypted(stored: str) -> str:
    s = (stored or "").strip()
    if s.startswith("gAAAAA"):
        try:
            return decrypt_signing_secret(s)
        except Exception:  # noqa: BLE001
            return ""
    return s


def get_inbound_webhook_secret(provider: str) -> str:
    """Return plaintext signing secret for inbound verification."""

    if provider == "pindora_lock":
        configured = (current_app.config.get("PINDORA_LOCK_WEBHOOK_SECRET") or "").strip()
        if configured:
            return configured

    key = _INBOUND_SETTING_KEY.get(provider)
    if key:
        raw = settings_service.get(key, default="")
        if isinstance(raw, str) and raw.strip():
            decrypted = _decrypt_if_encrypted(raw)
            if decrypted:
                return decrypted

    return ""


def persist_inbound_webhook_secret(
    *,
    provider: str,
    plaintext: str,
    actor_user_id: int | None,
) -> None:
    """Encrypt and store an inbound provider secret in Settings (never plaintext at rest)."""

    key = _INBOUND_SETTING_KEY.get(provider)
    if not key:
        raise ValueError(f"Unknown webhook provider: {provider}")
    enc = encrypt_signing_secret(plaintext)
    settings_service.set_value(
        key,
        enc,
        type_=SettingType.STRING,
        description=f"Inbound webhook signing secret for {provider}",
        is_secret=True,
        actor_user_id=actor_user_id,
    )
    if provider == "pindora_lock":
        current_app.config["PINDORA_LOCK_WEBHOOK_SECRET"] = plaintext


def _payload_hash(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def record_inbound_event(
    *,
    provider: str,
    event_type: str,
    external_id: str | None,
    payload: dict[str, Any],
    signature: str,
    signature_verified: bool,
    organization_id: int | None,
) -> WebhookEvent:
    """Persist (or return existing) ``WebhookEvent`` and audit ``webhook.received`` once."""

    sig_store = _truncate(signature, 256) or ""

    if external_id:
        existing = (
            WebhookEvent.query.filter_by(provider=provider, external_id=external_id)
            .order_by(WebhookEvent.id.asc())
            .first()
        )
        if existing is not None:
            audit_record(
                "webhook.duplicate_ignored",
                status=AuditStatus.SUCCESS,
                organization_id=existing.organization_id,
                target_type="webhook_event",
                target_id=existing.id,
                metadata={"provider": provider, "external_id": external_id},
            )
            return existing

    event = WebhookEvent(
        provider=provider,
        event_type=event_type,
        external_id=external_id,
        payload=payload,
        signature=sig_store,
        signature_verified=signature_verified,
        organization_id=organization_id,
    )
    db.session.add(event)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        existing = (
            WebhookEvent.query.filter_by(provider=provider, external_id=external_id)
            .order_by(WebhookEvent.id.asc())
            .first()
        )
        if existing is not None:
            return existing
        raise

    audit_record(
        "webhook.received",
        status=AuditStatus.SUCCESS,
        organization_id=organization_id,
        target_type="webhook_event",
        target_id=event.id,
        metadata={"provider": provider, "event_type": event_type},
    )
    return event


def provider_is_known(provider: str) -> bool:
    return provider in {"stripe", "paytrail", "vismapay", "pindora_lock"}


def mark_processed(event_id: int, error: str | None) -> None:
    event = WebhookEvent.query.get(event_id)
    if event is None:
        return
    now = _now()
    event.processed = True
    event.processed_at = now
    if error is None:
        event.processing_error = None
        audit_record(
            "webhook.processed",
            status=AuditStatus.SUCCESS,
            organization_id=event.organization_id,
            target_type="webhook_event",
            target_id=event_id,
            metadata={"provider": event.provider, "event_type": event.event_type},
        )
    else:
        event.processing_error = error
        audit_record(
            "webhook.failed",
            status=AuditStatus.FAILURE,
            organization_id=event.organization_id,
            target_type="webhook_event",
            target_id=event_id,
            metadata={
                "provider": event.provider,
                "event_type": event.event_type,
                "error": _truncate(error, _ERROR_AUDIT_MAX) or "error",
            },
        )


def _canonical_body_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _send_http(
    *,
    url: str,
    body_bytes: bytes,
    signature_hex: str,
    timeout_seconds: float,
) -> tuple[int | None, str | None]:
    try:
        resp = requests.post(
            url,
            data=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Pindora-Signature": signature_hex,
            },
            timeout=timeout_seconds,
        )
        body = (resp.text or "")[:_RESPONSE_BODY_MAX]
        return resp.status_code, body
    except requests.RequestException as exc:
        return None, _truncate(str(exc), _RESPONSE_BODY_MAX)


def _subscription_signing_secret(sub: WebhookSubscription) -> str:
    return decrypt_signing_secret(sub.secret_encrypted)


def dispatch(
    subscription_id: int,
    event_type: str,
    payload: dict[str, Any],
    *,
    http_post: Any | None = None,
) -> WebhookDelivery:
    """Deliver one outbound webhook (first attempt synchronous)."""

    poster = http_post or _send_http
    sub = WebhookSubscription.query.get(subscription_id)
    if sub is None:
        raise ValueError("subscription_not_found")
    if not sub.is_active:
        raise ValueError("subscription_inactive")

    events_list = sub.events if isinstance(sub.events, list) else []
    if event_type not in events_list:
        raise ValueError("event_type_not_subscribed")

    secret = _subscription_signing_secret(sub)
    phash = _payload_hash(payload)
    body_bytes = _canonical_body_bytes(payload)
    signature_hex = hmac_sha256_hex_digest(secret=secret, payload_bytes=body_bytes)

    delivery = WebhookDelivery(
        subscription_id=sub.id,
        event_type=event_type,
        payload=payload,
        payload_hash=phash,
        signature=signature_hex[:256],
        attempt_number=1,
    )
    db.session.add(delivery)
    db.session.flush()

    timeout_s = min(4.0, float(current_app.config.get("WEBHOOK_HTTP_TIMEOUT_SECONDS", 4.0)))
    status, body = poster(
        url=sub.url,
        body_bytes=body_bytes,
        signature_hex=signature_hex,
        timeout_seconds=timeout_s,
    )

    ok = status is not None and 200 <= int(status) < 300
    delivery.response_status = status
    delivery.response_body = body

    if ok:
        delivery.delivered_at = _now()
        delivery.next_retry_at = None
        sub.last_delivery_at = delivery.delivered_at
        sub.last_delivery_status = status
        sub.failure_count = 0
    else:
        delivery.next_retry_at = _now() + timedelta(seconds=_BACKOFF_SECONDS[0])
        sub.last_delivery_status = status
        sub.failure_count = int(sub.failure_count or 0) + 1
        if sub.failure_count >= 5:
            sub.is_active = False
            delivery.next_retry_at = None
            audit_record(
                "webhook.subscription_disabled",
                status=AuditStatus.FAILURE,
                organization_id=sub.organization_id,
                target_type="webhook_subscription",
                target_id=sub.id,
                metadata={"reason": "max_failures"},
                commit=False,
            )

    sub.updated_at = _now()
    db.session.commit()

    audit_record(
        "webhook.dispatched",
        status=AuditStatus.SUCCESS if ok else AuditStatus.FAILURE,
        organization_id=sub.organization_id,
        target_type="webhook_delivery",
        target_id=delivery.id,
        metadata={
            "event_type": event_type,
            "subscription_id": sub.id,
            "http_status": status,
        },
    )
    return delivery


def retry_pending_deliveries(*, http_post: Any | None = None) -> int:
    """POST retries for failed outbound deliveries; disable subscription after 5 failures."""

    poster = http_post or _send_http
    now = _now()
    rows = (
        WebhookDelivery.query.filter(
            WebhookDelivery.delivered_at.is_(None),
            WebhookDelivery.next_retry_at.isnot(None),
            WebhookDelivery.next_retry_at <= now,
        )
        .order_by(WebhookDelivery.next_retry_at.asc(), WebhookDelivery.id.asc())
        .limit(200)
        .all()
    )
    processed = 0
    for delivery in rows:
        sub = WebhookSubscription.query.get(delivery.subscription_id)
        if sub is None or not sub.is_active:
            delivery.next_retry_at = None
            db.session.commit()
            continue

        secret = _subscription_signing_secret(sub)
        body_bytes = _canonical_body_bytes(delivery.payload if isinstance(delivery.payload, dict) else {})
        signature_hex = hmac_sha256_hex_digest(secret=secret, payload_bytes=body_bytes)
        delivery.attempt_number = int(delivery.attempt_number or 0) + 1
        timeout_s = min(4.0, float(current_app.config.get("WEBHOOK_HTTP_TIMEOUT_SECONDS", 4.0)))
        status, body = poster(
            url=sub.url,
            body_bytes=body_bytes,
            signature_hex=signature_hex,
            timeout_seconds=timeout_s,
        )
        ok = status is not None and 200 <= int(status) < 300
        delivery.response_status = status
        delivery.response_body = body

        if ok:
            delivery.delivered_at = now
            delivery.next_retry_at = None
            sub.last_delivery_at = now
            sub.last_delivery_status = status
            sub.failure_count = 0
        else:
            idx = min(delivery.attempt_number - 1, len(_BACKOFF_SECONDS) - 1)
            delivery.next_retry_at = now + timedelta(seconds=_BACKOFF_SECONDS[idx])
            sub.failure_count = int(sub.failure_count or 0) + 1
            sub.last_delivery_status = status

            if sub.failure_count >= 5:
                sub.is_active = False
                delivery.next_retry_at = None
                audit_record(
                    "webhook.subscription_disabled",
                    status=AuditStatus.FAILURE,
                    organization_id=sub.organization_id,
                    target_type="webhook_subscription",
                    target_id=sub.id,
                    metadata={"reason": "max_failures"},
                    commit=False,
                )

        sub.updated_at = now
        db.session.commit()
        processed += 1

    return processed


def create_outbound_subscription(
    *,
    organization_id: int,
    url: str,
    events: list[str],
    created_by_user_id: int | None,
) -> tuple[WebhookSubscription, str]:
    """Create subscription; returns ``(row, plaintext_secret_once)``."""

    raw_secret = secrets.token_urlsafe(32)
    secret_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
    enc = encrypt_signing_secret(raw_secret)
    sub = WebhookSubscription(
        organization_id=organization_id,
        url=url.strip()[:512],
        secret_hash=secret_hash,
        secret_encrypted=enc,
        events=list(events),
        is_active=True,
        created_by_user_id=created_by_user_id,
    )
    db.session.add(sub)
    db.session.commit()
    return sub, raw_secret


def deactivate_outbound_subscription(*, subscription_id: int, organization_id: int) -> bool:
    sub = WebhookSubscription.query.filter_by(
        id=subscription_id,
        organization_id=organization_id,
    ).first()
    if sub is None:
        return False
    sub.is_active = False
    sub.updated_at = _now()
    db.session.commit()
    return True


def list_subscriptions_for_org(*, organization_id: int) -> list[WebhookSubscription]:
    return (
        WebhookSubscription.query.filter_by(organization_id=organization_id)
        .order_by(WebhookSubscription.id.desc())
        .all()
    )


def list_recent_deliveries(*, subscription_id: int, limit: int = 10) -> list[WebhookDelivery]:
    return (
        WebhookDelivery.query.filter_by(subscription_id=subscription_id)
        .order_by(WebhookDelivery.id.desc())
        .limit(limit)
        .all()
    )


def apply_idempotency_for_inbound(
    *,
    provider: str,
    external_id: str,
    payload: dict[str, Any],
    organization_id: int | None,
) -> None:
    """Reserve idempotency row for duplicate inbound deliveries (Prompt 7B)."""

    endpoint = f"POST /api/v1/webhooks/{provider}"
    key = f"webhook:{provider}:{external_id}"
    body_hash = _payload_hash(payload)
    get_or_create(key, endpoint, body_hash, organization_id=organization_id)


def extract_event_metadata(
    provider: str, payload: dict[str, Any]
) -> tuple[str, str | None, int | None]:
    """Derive ``event_type``, ``external_id``, and optional ``organization_id``."""

    org_id: int | None = None
    for k in ("organization_id", "org_id"):
        raw = payload.get(k)
        if raw is not None and str(raw).strip() != "":
            try:
                org_id = int(raw)
            except (TypeError, ValueError):
                org_id = None
            break

    if provider == "stripe":
        et = str(payload.get("type") or "stripe.event")
        eid = payload.get("id")
        ext = str(eid) if eid is not None else None
        return et, ext, org_id

    if provider == "vismapay":
        et = str(payload.get("type") or payload.get("event_type") or "vismapay.event")
        eid = payload.get("id") or payload.get("order_number")
        ext = str(eid) if eid is not None else None
        return et, ext, org_id

    # pindora_lock
    et = str(payload.get("event") or payload.get("type") or "pindora_lock.event")
    eid = payload.get("id") or payload.get("event_id")
    ext = str(eid) if eid is not None else None
    return et, ext, org_id


def mark_inbound_handler_dead_letter(event: WebhookEvent, *, error: str | None = None) -> None:
    """Mark an inbound event as processed after too many handler failures (ops visibility)."""

    now = _now()
    event.processed = True
    event.processed_at = now
    event.processing_error = _truncate(error, _ERROR_AUDIT_MAX) or "handler_dead_letter"
    audit_record(
        "webhook.handler_dead_letter",
        status=AuditStatus.FAILURE,
        organization_id=event.organization_id,
        target_type="webhook_event",
        target_id=event.id,
        metadata={
            "provider": event.provider,
            "event_type": event.event_type,
            "attempts": int(event.inbound_handler_attempts or 0),
        },
    )


def process_stale_inbound_webhook_events(
    *,
    min_age_seconds: int = 30,
    batch_limit: int = 100,
) -> int:
    """Dispatch handlers for inbound events left ``processed=False`` (slow HTTP path or errors)."""

    cutoff = _now() - timedelta(seconds=max(5, min_age_seconds))
    rows = (
        WebhookEvent.query.filter(
            WebhookEvent.processed.is_(False),
            WebhookEvent.created_at <= cutoff,
        )
        .order_by(WebhookEvent.id.asc())
        .limit(batch_limit)
        .all()
    )
    handled = 0
    for event in rows:
        if int(event.inbound_handler_attempts or 0) >= 5:
            mark_inbound_handler_dead_letter(event, error=event.processing_error)
            db.session.commit()
            handled += 1
            continue
        try:
            dispatch_handler(
                provider=event.provider,
                event=event,
                payload=event.payload if isinstance(event.payload, dict) else {},
            )
            mark_processed(event.id, None)
        except Exception as exc:  # noqa: BLE001
            err = str(exc)[:512]
            event.inbound_handler_attempts = int(event.inbound_handler_attempts or 0) + 1
            event.processing_error = err
            if event.inbound_handler_attempts >= 5:
                mark_inbound_handler_dead_letter(event, error=err)
        db.session.commit()
        handled += 1
    return handled
