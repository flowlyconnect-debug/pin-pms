"""Public API routes served under ``/api/v1``.

Minimum surface required by the project brief (section 6):

* ``GET /api/v1/health`` — unauthenticated liveness check.
* ``GET /api/v1/me``     — returns the context of the API key making the call.
"""

from __future__ import annotations

from flask import Response, current_app, g, request

from app.api import api_bp
from app.api.auth import require_api_key, scope_required
from app.api.schemas import json_error, json_ok
from app.billing import services as billing_service
from app.integrations.ical.service import IcalService, IcalServiceError
from app.maintenance import services as maintenance_service
from app.properties import services as property_service
from app.reservations import services as reservation_service
from app.status.service import readiness_status


@api_bp.get("/health")
def api_health():
    """Liveness probe: process is serving requests."""

    return json_ok({"status": "ok"})


@api_bp.get("/health/ready")
def api_health_ready():
    payload = readiness_status(current_app)
    status = 200 if payload["ok"] else 503
    return json_ok(payload, status=status)


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
            "last_used_at": (api_key.last_used_at.isoformat() if api_key.last_used_at else None),
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


def _billing_actor_user_id() -> int | None:
    """User id for billing audit columns; falls back to API key owner."""

    uid = _actor_user_id()
    if uid is not None:
        return uid
    api_key = getattr(g, "api_key", None)
    if api_key is not None and api_key.user_id is not None:
        return api_key.user_id
    return None


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
@scope_required("properties:read")
def list_properties():
    page, per_page = _pagination_params()
    if page is None or per_page is None:
        return json_error(
            "validation_error",
            "Query params 'page' and 'per_page' must be positive integers.",
            status=400,
        )

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
@scope_required("properties:write")
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
@scope_required("properties:read")
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
@scope_required("properties:read")
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
@scope_required("properties:write")
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


@api_bp.get("/units/<int:unit_id>/calendar.ics")
def export_unit_calendar_ics(unit_id: int):
    token = (request.args.get("token") or "").strip()
    service = IcalService()
    try:
        if not service.verify_unit_token(unit_id=unit_id, token=token):
            return json_error("forbidden", "Invalid calendar token.", status=403)
        payload = service.export_unit_calendar(unit_id=unit_id)
    except IcalServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return Response(payload, mimetype="text/calendar; charset=utf-8")


@api_bp.get("/reservations")
@require_api_key
@scope_required("reservations:read")
def list_reservations():
    page, per_page = _pagination_params()
    if page is None or per_page is None:
        return json_error(
            "validation_error",
            "Query params 'page' and 'per_page' must be positive integers.",
            status=400,
        )

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
@scope_required("reservations:write")
def create_reservation():
    payload = _payload()
    try:
        unit_id = int(payload.get("unit_id", 0))
        guest_id = int(payload.get("guest_id", 0))
    except (TypeError, ValueError):
        return json_error(
            "validation_error", "Fields 'unit_id' and 'guest_id' must be integers.", status=400
        )

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
@scope_required("reservations:read")
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
@scope_required("reservations:write")
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


@api_bp.get("/leases")
@require_api_key
@scope_required("invoices:read")
def list_leases():
    page, per_page = _pagination_params()
    if page is None or per_page is None:
        return json_error(
            "validation_error",
            "Query params 'page' and 'per_page' must be positive integers.",
            status=400,
        )
    data, total = billing_service.list_leases_paginated(
        organization_id=_org_id(),
        page=page,
        per_page=per_page,
    )
    return json_ok(data, meta={"page": page, "per_page": per_page, "total": total})


@api_bp.post("/leases")
@require_api_key
@scope_required("invoices:write")
def create_lease_api():
    actor = _billing_actor_user_id()
    if actor is None:
        return json_error(
            "validation_error",
            "API key must be linked to a user to create leases.",
            status=400,
        )
    payload = _payload()
    try:
        reservation_id = payload.get("reservation_id")
        res_id = int(reservation_id) if reservation_id not in (None, "") else None
        data = billing_service.create_lease(
            organization_id=_org_id(),
            unit_id=int(payload.get("unit_id", 0)),
            guest_id=int(payload.get("guest_id", 0)),
            reservation_id=res_id,
            start_date_raw=str(payload.get("start_date", "")),
            end_date_raw=str(payload.get("end_date", "")) if payload.get("end_date") else None,
            rent_amount_raw=payload.get("rent_amount"),
            deposit_amount_raw=payload.get("deposit_amount"),
            billing_cycle=str(payload.get("billing_cycle", "monthly")),
            notes=str(payload.get("notes", "")) if payload.get("notes") is not None else None,
            actor_user_id=actor,
        )
    except (TypeError, ValueError):
        return json_error("validation_error", "unit_id and guest_id must be integers.", status=400)
    except billing_service.LeaseServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data, status=201)


@api_bp.get("/leases/<int:lease_id>")
@require_api_key
@scope_required("invoices:read")
def get_lease_api(lease_id: int):
    try:
        data = billing_service.get_lease_for_org(
            organization_id=_org_id(),
            lease_id=lease_id,
        )
    except billing_service.LeaseServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data)


@api_bp.patch("/leases/<int:lease_id>")
@require_api_key
@scope_required("invoices:write")
def patch_lease_api(lease_id: int):
    actor = _billing_actor_user_id()
    if actor is None:
        return json_error(
            "validation_error",
            "API key must be linked to a user to update leases.",
            status=400,
        )
    body = _payload()
    if not body:
        return json_error(
            "validation_error", "JSON body with at least one field is required.", status=400
        )
    allowed = {
        "unit_id",
        "guest_id",
        "reservation_id",
        "start_date",
        "end_date",
        "rent_amount",
        "deposit_amount",
        "billing_cycle",
        "notes",
    }
    data = {k: body[k] for k in body if k in allowed}
    if "unit_id" in data:
        try:
            data["unit_id"] = int(data["unit_id"])
        except (TypeError, ValueError):
            return json_error("validation_error", "unit_id must be an integer.", status=400)
    if "guest_id" in data:
        try:
            data["guest_id"] = int(data["guest_id"])
        except (TypeError, ValueError):
            return json_error("validation_error", "guest_id must be an integer.", status=400)
    if "reservation_id" in data and data["reservation_id"] not in (None, ""):
        try:
            data["reservation_id"] = int(data["reservation_id"])
        except (TypeError, ValueError):
            return json_error("validation_error", "reservation_id must be an integer.", status=400)
    try:
        out = billing_service.update_lease(
            organization_id=_org_id(),
            lease_id=lease_id,
            data=data,
            actor_user_id=actor,
        )
    except billing_service.LeaseServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(out)


@api_bp.get("/invoices")
@require_api_key
@scope_required("invoices:read")
def list_invoices():
    page, per_page = _pagination_params()
    if page is None or per_page is None:
        return json_error(
            "validation_error",
            "Query params 'page' and 'per_page' must be positive integers.",
            status=400,
        )
    data, total = billing_service.list_invoices_paginated(
        organization_id=_org_id(),
        page=page,
        per_page=per_page,
    )
    return json_ok(data, meta={"page": page, "per_page": per_page, "total": total})


@api_bp.post("/invoices")
@require_api_key
@scope_required("invoices:write")
def create_invoice_api():
    actor = _billing_actor_user_id()
    if actor is None:
        return json_error(
            "validation_error",
            "API key must be linked to a user to create invoices.",
            status=400,
        )
    payload = _payload()
    lease_id = payload.get("lease_id")
    lid = int(lease_id) if lease_id not in (None, "") else None
    try:
        if lid is not None:
            data = billing_service.create_invoice_for_lease(
                organization_id=_org_id(),
                lease_id=lid,
                amount_raw=payload.get("amount"),
                due_date_raw=str(payload.get("due_date", "")),
                currency=str(payload.get("currency")) if payload.get("currency") else None,
                description=str(payload.get("description")) if payload.get("description") else None,
                status=str(payload.get("status", "open")),
                actor_user_id=actor,
            )
        else:
            res_raw = payload.get("reservation_id")
            guest_raw = payload.get("guest_id")
            data = billing_service.create_invoice(
                organization_id=_org_id(),
                amount_raw=payload.get("amount"),
                due_date_raw=str(payload.get("due_date", "")),
                currency=str(payload.get("currency")) if payload.get("currency") else None,
                description=str(payload.get("description")) if payload.get("description") else None,
                lease_id=None,
                reservation_id=int(res_raw) if res_raw not in (None, "") else None,
                guest_id=int(guest_raw) if guest_raw not in (None, "") else None,
                status=str(payload.get("status", "draft")),
                metadata_json=payload.get("metadata_json"),
                actor_user_id=actor,
            )
    except (TypeError, ValueError):
        return json_error("validation_error", "Invalid numeric id in payload.", status=400)
    except billing_service.InvoiceServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data, status=201)


@api_bp.get("/invoices/<int:invoice_id>")
@require_api_key
@scope_required("invoices:read")
def get_invoice_api(invoice_id: int):
    try:
        data = billing_service.get_invoice_for_org(
            organization_id=_org_id(),
            invoice_id=invoice_id,
        )
    except billing_service.InvoiceServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data)


@api_bp.post("/invoices/<int:invoice_id>/mark-paid")
@require_api_key
@scope_required("invoices:write")
def mark_invoice_paid_api(invoice_id: int):
    actor = _billing_actor_user_id()
    try:
        data = billing_service.mark_invoice_paid(
            organization_id=_org_id(),
            invoice_id=invoice_id,
            actor_user_id=actor,
        )
    except billing_service.InvoiceServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data)


@api_bp.post("/invoices/<int:invoice_id>/cancel")
@require_api_key
@scope_required("invoices:write")
def cancel_invoice_api(invoice_id: int):
    actor = _billing_actor_user_id()
    try:
        data = billing_service.cancel_invoice(
            organization_id=_org_id(),
            invoice_id=invoice_id,
            actor_user_id=actor,
        )
    except billing_service.InvoiceServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data)


# --- Maintenance requests ---------------------------------------------------


@api_bp.get("/maintenance-requests")
@require_api_key
@scope_required("maintenance:read")
def list_maintenance_requests_api():
    page, per_page = _pagination_params()
    if page is None or per_page is None:
        return json_error(
            "validation_error",
            "Query params 'page' and 'per_page' must be positive integers.",
            status=400,
        )
    status = (request.args.get("status") or "").strip() or None
    priority = (request.args.get("priority") or "").strip() or None
    property_id_raw = request.args.get("property_id")
    unit_id_raw = request.args.get("unit_id")
    try:
        property_id = int(property_id_raw) if property_id_raw not in (None, "") else None
        unit_id = int(unit_id_raw) if unit_id_raw not in (None, "") else None
        data, total = maintenance_service.list_maintenance_requests_paginated(
            organization_id=_org_id(),
            page=page,
            per_page=per_page,
            status=status,
            priority=priority,
            property_id=property_id,
            unit_id=unit_id,
        )
    except ValueError:
        return json_error(
            "validation_error", "property_id and unit_id must be integers.", status=400
        )
    return json_ok(data, meta={"page": page, "per_page": per_page, "total": total})


@api_bp.post("/maintenance-requests")
@require_api_key
@scope_required("maintenance:write")
def create_maintenance_request_api():
    actor = _billing_actor_user_id()
    if actor is None:
        return json_error(
            "validation_error",
            "API key must be linked to a user to create maintenance requests.",
            status=400,
        )
    payload = _payload()
    try:
        unit_raw = payload.get("unit_id")
        guest_raw = payload.get("guest_id")
        res_raw = payload.get("reservation_id")
        assign_raw = payload.get("assigned_to_id")
        data = maintenance_service.create_maintenance_request(
            organization_id=_org_id(),
            property_id=int(payload.get("property_id", 0)),
            unit_id=int(unit_raw) if unit_raw not in (None, "") else None,
            guest_id=int(guest_raw) if guest_raw not in (None, "") else None,
            reservation_id=int(res_raw) if res_raw not in (None, "") else None,
            title=str(payload.get("title", "")),
            description=(
                str(payload.get("description")) if payload.get("description") is not None else None
            ),
            priority=str(payload.get("priority", "normal")),
            status=str(payload.get("status", "new")),
            due_date_raw=(
                str(payload.get("due_date")) if payload.get("due_date") is not None else None
            ),
            assigned_to_id=int(assign_raw) if assign_raw not in (None, "") else None,
            actor_user_id=actor,
        )
    except (TypeError, ValueError):
        return json_error("validation_error", "Invalid numeric id in payload.", status=400)
    except maintenance_service.MaintenanceServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data, status=201)


@api_bp.get("/maintenance-requests/<int:request_id>")
@require_api_key
@scope_required("maintenance:read")
def get_maintenance_request_api(request_id: int):
    try:
        data = maintenance_service.get_maintenance_request(
            organization_id=_org_id(),
            request_id=request_id,
        )
    except maintenance_service.MaintenanceServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data)


@api_bp.patch("/maintenance-requests/<int:request_id>")
@require_api_key
@scope_required("maintenance:write")
def patch_maintenance_request_api(request_id: int):
    actor = _billing_actor_user_id()
    if actor is None:
        return json_error(
            "validation_error",
            "API key must be linked to a user to update maintenance requests.",
            status=400,
        )
    body = _payload()
    if not body:
        return json_error(
            "validation_error", "JSON body with at least one field is required.", status=400
        )
    allowed = {
        "title",
        "description",
        "priority",
        "status",
        "property_id",
        "unit_id",
        "guest_id",
        "reservation_id",
        "due_date",
        "assigned_to_id",
    }
    data = {k: body[k] for k in body if k in allowed}
    try:
        out = maintenance_service.update_maintenance_request(
            organization_id=_org_id(),
            request_id=request_id,
            data=data,
            actor_user_id=actor,
        )
    except maintenance_service.MaintenanceServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(out)


@api_bp.post("/maintenance-requests/<int:request_id>/resolve")
@require_api_key
@scope_required("maintenance:write")
def resolve_maintenance_request_api(request_id: int):
    actor = _billing_actor_user_id()
    if actor is None:
        return json_error(
            "validation_error",
            "API key must be linked to a user to resolve maintenance requests.",
            status=400,
        )
    try:
        data = maintenance_service.resolve_maintenance_request(
            organization_id=_org_id(),
            request_id=request_id,
            actor_user_id=actor,
        )
    except maintenance_service.MaintenanceServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data)


@api_bp.post("/maintenance-requests/<int:request_id>/cancel")
@require_api_key
@scope_required("maintenance:write")
def cancel_maintenance_request_api(request_id: int):
    actor = _billing_actor_user_id()
    if actor is None:
        return json_error(
            "validation_error",
            "API key must be linked to a user to cancel maintenance requests.",
            status=400,
        )
    try:
        data = maintenance_service.cancel_maintenance_request(
            organization_id=_org_id(),
            request_id=request_id,
            actor_user_id=actor,
        )
    except maintenance_service.MaintenanceServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data)
