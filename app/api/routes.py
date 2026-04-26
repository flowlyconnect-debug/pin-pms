"""Public API routes served under ``/api/v1``.

Minimum surface required by the project brief (section 6):

* ``GET /api/v1/health`` — unauthenticated liveness check.
* ``GET /api/v1/me``     — returns the context of the API key making the call.
"""
from __future__ import annotations

from flask import g, request

from app.api import api_bp
from app.api.auth import require_api_key
from app.api.schemas import json_error, json_ok
from app.properties import services as property_service
from app.reservations import services as reservation_service


@api_bp.get("/health")
def api_health():
    """Liveness probe. Intentionally open — does not expose any tenant data."""

    return json_ok({"status": "ok"})


@api_bp.get("/me")
@require_api_key
def api_me():
    """Return who the calling API key belongs to."""

    api_key = g.api_key

    user_payload = None
    if api_key.user is not None:
        user_payload = {
            "id": api_key.user.id,
            "email": api_key.user.email,
            "role": api_key.user.role,
        }

    data = {
        "api_key": {
            "id": api_key.id,
            "name": api_key.name,
            "prefix": api_key.key_prefix,
            "scopes": api_key.scope_list,
            "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
            "last_used_at": (
                api_key.last_used_at.isoformat() if api_key.last_used_at else None
            ),
        },
        "organization": {
            "id": api_key.organization_id,
            "name": api_key.organization.name,
        },
        "user": user_payload,
    }
    return json_ok(data)


def _payload() -> dict:
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def _org_id() -> int:
    return g.api_key.organization_id


def _actor_user_id() -> int | None:
    user = getattr(g, "api_user", None)
    return user.id if user is not None else None


def _pagination_params() -> tuple[int, int] | tuple[None, None]:
    try:
        page = int(request.args.get("page", "1"))
        per_page = int(request.args.get("per_page", "20"))
    except ValueError:
        return None, None

    if page < 1 or per_page < 1:
        return None, None
    return page, min(per_page, 100)


@api_bp.get("/properties")
@require_api_key
def list_properties():
    page, per_page = _pagination_params()
    if page is None or per_page is None:
        return json_error("validation_error", "Query params 'page' and 'per_page' must be positive integers.", status=400)

    data, total = property_service.list_properties_paginated(
        organization_id=_org_id(),
        page=page,
        per_page=per_page,
    )
    return json_ok(
        data,
        meta={"page": page, "per_page": per_page, "total": total},
    )


@api_bp.post("/properties")
@require_api_key
def create_property():
    payload = _payload()
    try:
        data = property_service.create_property(
            organization_id=_org_id(),
            name=payload.get("name", ""),
            address=payload.get("address"),
            actor_user_id=_actor_user_id(),
        )
    except property_service.PropertyServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data, status=201)


@api_bp.get("/properties/<int:property_id>")
@require_api_key
def get_property(property_id: int):
    try:
        data = property_service.get_property(
            organization_id=_org_id(),
            property_id=property_id,
        )
    except property_service.PropertyServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data)


@api_bp.get("/properties/<int:property_id>/units")
@require_api_key
def list_units(property_id: int):
    try:
        data = property_service.list_units(
            organization_id=_org_id(),
            property_id=property_id,
        )
    except property_service.PropertyServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data)


@api_bp.post("/properties/<int:property_id>/units")
@require_api_key
def create_unit(property_id: int):
    payload = _payload()
    try:
        data = property_service.create_unit(
            organization_id=_org_id(),
            property_id=property_id,
            name=payload.get("name", ""),
            unit_type=payload.get("unit_type"),
            actor_user_id=_actor_user_id(),
        )
    except property_service.PropertyServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data, status=201)


@api_bp.get("/reservations")
@require_api_key
def list_reservations():
    page, per_page = _pagination_params()
    if page is None or per_page is None:
        return json_error("validation_error", "Query params 'page' and 'per_page' must be positive integers.", status=400)

    data, total = reservation_service.list_reservations_paginated(
        organization_id=_org_id(),
        page=page,
        per_page=per_page,
    )
    return json_ok(
        data,
        meta={"page": page, "per_page": per_page, "total": total},
    )


@api_bp.post("/reservations")
@require_api_key
def create_reservation():
    payload = _payload()
    try:
        unit_id = int(payload.get("unit_id", 0))
        guest_id = int(payload.get("guest_id", 0))
    except (TypeError, ValueError):
        return json_error("validation_error", "Fields 'unit_id' and 'guest_id' must be integers.", status=400)

    try:
        data = reservation_service.create_reservation(
            organization_id=_org_id(),
            unit_id=unit_id,
            guest_id=guest_id,
            start_date_raw=payload.get("start_date", ""),
            end_date_raw=payload.get("end_date", ""),
            actor_user_id=_actor_user_id(),
        )
    except reservation_service.ReservationServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data, status=201)


@api_bp.get("/reservations/<int:reservation_id>")
@require_api_key
def get_reservation(reservation_id: int):
    try:
        data = reservation_service.get_reservation(
            organization_id=_org_id(),
            reservation_id=reservation_id,
        )
    except reservation_service.ReservationServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data)


@api_bp.patch("/reservations/<int:reservation_id>/cancel")
@require_api_key
def cancel_reservation(reservation_id: int):
    try:
        data = reservation_service.cancel_reservation(
            organization_id=_org_id(),
            reservation_id=reservation_id,
            actor_user_id=_actor_user_id(),
        )
    except reservation_service.ReservationServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data)
