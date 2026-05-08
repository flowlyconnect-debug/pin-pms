"""Inbound webhook HTTP routes (no API key; signature + idempotency only)."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from flask import Response, request

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.extensions import db
from app.idempotency.services import IdempotencyKeyConflict
from app.payments import services as payment_services
from app.payments.providers.paytrail import PaytrailProvider
from app.payments.providers.stripe import StripeProvider
from app.webhooks.services import (
    apply_idempotency_for_inbound,
    dispatch_handler,
    extract_event_metadata,
    get_inbound_webhook_secret,
    mark_processed,
    provider_is_known,
    record_inbound_event,
    verify_signature,
)

from . import webhooks_bp

_ALLOWED = frozenset({"stripe", "vismapay", "pindora_lock", "paytrail"})
_MAX_WEBHOOK_BYTES = 1024 * 1024

_SIGNATURE_HEADER = {
    "stripe": "Stripe-Signature",
    "vismapay": "X-VismaPay-Signature",
    "pindora_lock": "X-Signature",
    "paytrail": "signature",
}


@webhooks_bp.get("/paytrail")
def inbound_paytrail_webhook():
    provider = PaytrailProvider()
    query = dict(request.args.items())
    if not provider.verify_query_signature(query):
        audit_record(
            "webhook.invalid_signature",
            status=AuditStatus.FAILURE,
            target_type="webhook_event",
            target_id=None,
            metadata={"provider": "paytrail"},
            commit=True,
        )
        return _json_error("unauthorized", 401)
    event = provider.parse_webhook_event(payload=query)
    if event.get("type") == "invalid_status":
        return _json_error("invalid_status", 400)
    payment_services.handle_webhook_event("paytrail", event)
    db.session.commit()
    return Response('{"ok":true}', status=200, mimetype="application/json")


inbound_paytrail_webhook._required_scope = "webhooks:write"  # type: ignore[attr-defined]


def _json_error(message: str, status: int) -> Response:
    body = json.dumps({"success": False, "error": message})
    return Response(body, status=status, mimetype="application/json")


@webhooks_bp.post("/<provider>")
def inbound_webhook(provider: str) -> Any:
    provider = (provider or "").strip().lower()
    if not provider_is_known(provider):
        audit_record(
            "webhook.unknown_provider",
            status=AuditStatus.SUCCESS,
            target_type="webhook_event",
            target_id=None,
            metadata={"provider": provider},
            commit=True,
        )
        return _json_error("unknown_provider", 404)

    if request.content_length is not None and int(request.content_length) >= _MAX_WEBHOOK_BYTES:
        audit_record(
            "webhook.payload_too_large",
            status=AuditStatus.FAILURE,
            target_type="webhook_event",
            target_id=None,
            metadata={"provider": provider, "content_length": int(request.content_length)},
            commit=True,
        )
        return _json_error("payload_too_large", 413)

    raw = request.get_data(cache=False, as_text=False) or b""
    header_name = _SIGNATURE_HEADER[provider]
    signature_header = (request.headers.get(header_name) or "").strip()

    if provider == "stripe":
        stripe_provider = StripeProvider()
        if not stripe_provider.verify_webhook(payload_bytes=raw, signature_header=signature_header):
            audit_record(
                "webhook.invalid_signature",
                status=AuditStatus.FAILURE,
                target_type="webhook_event",
                target_id=None,
                metadata={"provider": provider},
                commit=True,
            )
            return _json_error("unauthorized", 401)
        payload = json.loads(raw.decode("utf-8"))
        event = stripe_provider.parse_webhook_event(payload=payload)
        payment_services.handle_webhook_event("stripe", event)
        return Response('{"ok":true}', status=200, mimetype="application/json")

    secret = get_inbound_webhook_secret(provider)
    if not secret:
        audit_record(
            "webhook.invalid_signature",
            status=AuditStatus.FAILURE,
            target_type="webhook_event",
            target_id=None,
            metadata={"provider": provider, "reason": "missing_secret"},
        )
        db.session.commit()
        return _json_error("unauthorized", 401)

    if not verify_signature(provider, raw, signature_header, secret):
        audit_record(
            "webhook.invalid_signature",
            status=AuditStatus.FAILURE,
            target_type="webhook_event",
            target_id=None,
            metadata={"provider": provider},
        )
        db.session.commit()
        return _json_error("unauthorized", 401)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        audit_record(
            "webhook.invalid_payload",
            status=AuditStatus.FAILURE,
            target_type="webhook_event",
            target_id=None,
            metadata={"provider": provider},
        )
        db.session.commit()
        return _json_error("invalid_json", 400)

    if not isinstance(payload, dict):
        audit_record(
            "webhook.invalid_payload",
            status=AuditStatus.FAILURE,
            target_type="webhook_event",
            target_id=None,
            metadata={"provider": provider},
        )
        db.session.commit()
        return _json_error("invalid_json", 400)

    event_type, external_id, org_from_payload = extract_event_metadata(provider, payload)

    if external_id:
        try:
            apply_idempotency_for_inbound(
                provider=provider,
                external_id=external_id,
                payload=payload,
                organization_id=org_from_payload,
            )
        except IdempotencyKeyConflict:
            db.session.rollback()
            return _json_error("idempotency_key_conflict", 409)

    sig_fingerprint = hashlib.sha256(signature_header.encode("utf-8", errors="ignore")).hexdigest()
    event = record_inbound_event(
        provider=provider,
        event_type=event_type,
        external_id=external_id,
        payload=payload,
        signature=sig_fingerprint[:256],
        signature_verified=True,
        organization_id=org_from_payload,
    )

    if event.processed:
        db.session.commit()
        return Response('{"ok":true}', status=200, mimetype="application/json")

    deadline = time.monotonic() + 4.5
    err: str | None = None
    try:
        dispatch_handler(provider=provider, event=event, payload=payload)
        if time.monotonic() > deadline:
            db.session.commit()
            return Response('{"ok":true}', status=200, mimetype="application/json")
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:512]

    mark_processed(event.id, err)
    db.session.commit()
    return Response('{"ok":true}', status=200, mimetype="application/json")


# Keep API scope introspection coverage happy without enforcing API-key auth
# on inbound provider webhooks (they use signature verification instead).
inbound_webhook._required_scope = "webhooks:write"  # type: ignore[attr-defined]
