from __future__ import annotations

from flask import g, request

from app.api import api_bp
from app.api.auth import require_api_key, scope_required
from app.api.schemas import json_error, json_ok
from app.idempotency.decorators import idempotent_post
from app.payments import services


@api_bp.post("/payments/checkout")
@require_api_key
@scope_required("payments:write")
@idempotent_post("checkout")
def payments_checkout():
    payload = request.get_json(silent=True) or {}
    provider = str(payload.get("provider") or "").strip().lower()
    if provider == "stripe" and not g.get("api_key"):
        return json_error("unauthorized", "API key required.", status=401)
    try:
        data = services.create_checkout(
            payload.get("invoice_id"),
            provider,
            payload.get("return_url"),
            payload.get("cancel_url"),
            actor_user_id=getattr(g, "api_user", None).id if getattr(g, "api_user", None) else None,
            idempotency_key=(request.headers.get("Idempotency-Key") or "").strip() or None,
        )
    except services.PaymentServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data)


@api_bp.get("/payments/<int:payment_id>")
@require_api_key
@scope_required("payments:read")
def get_payment(payment_id: int):
    try:
        row = services.get_payment_for_org(
            payment_id=payment_id, organization_id=g.api_key.organization_id
        )
    except services.PaymentServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(
        {
            "id": row.id,
            "invoice_id": row.invoice_id,
            "provider": row.provider,
            "status": row.status,
            "amount": str(row.amount),
            "currency": row.currency,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }
    )


@api_bp.post("/payments/<int:payment_id>/refund")
@require_api_key
@scope_required("payments:write")
def refund_payment(payment_id: int):
    payload = request.get_json(silent=True) or {}
    idem = (request.headers.get("Idempotency-Key") or "").strip() or None
    try:
        data = services.refund(
            payment_id,
            payload.get("amount"),
            payload.get("reason"),
            actor_user_id=getattr(g, "api_user", None).id if getattr(g, "api_user", None) else None,
            idempotency_key=idem,
        )
    except services.PaymentServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data)


