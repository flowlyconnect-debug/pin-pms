"""Public API routes served under ``/api/v1``.

Minimum surface required by the project brief (section 6):

* ``GET /api/v1/health`` — unauthenticated liveness check.
* ``GET /api/v1/me``     — returns the context of the API key making the call.
"""

from __future__ import annotations

from io import BytesIO

from flask import Response, current_app, g, request, send_file

from app.api import api_bp
from app.api.auth import require_api_key, scope_required
from app.api.schemas import json_error, json_ok
from app.api.services import get_unit_for_org_calendar_export
from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.billing import services as billing_service
from app.billing.models import Invoice
from app.billing.pdf import generate_invoice_pdf
from app.comments.models import Comment
from app.comments.services import CommentService, CommentServiceError
from app.core.decorators import require_api_tenant_entity
from app.extensions import db
from app.guests.models import Guest
from app.integrations.ical.service import IcalService, IcalServiceError
from app.maintenance import services as maintenance_service
from app.properties import images as property_image_service
from app.properties import services as property_service
from app.properties.models import Property, PropertyImage, Unit
from app.reservations import services as reservation_service
from app.reservations.models import Reservation
from app.status.service import readiness_status
from app.tags.models import GuestTag, PropertyTag, ReservationTag, Tag
from app.tags.services import TagService, TagServiceError


@api_bp.get("/health")
def api_health():
    """Liveness probe: process is serving requests."""

    return json_ok({"status": "ok"})


@api_bp.get("/health/ready")
@require_api_key
@scope_required("reports:read")
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


def _serialize_tag(row: Tag) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "name": row.name,
        "color": row.color,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_comment(row: Comment) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "author_user_id": row.author_user_id,
        "body": row.body,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "edited_at": row.edited_at.isoformat() if row.edited_at else None,
        "is_internal": row.is_internal,
    }


def _serialize_property_image(row: PropertyImage) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "property_id": row.property_id,
        "url": row.url,
        "thumbnail_url": row.thumbnail_url,
        "alt_text": row.alt_text,
        "sort_order": row.sort_order,
        "file_size": row.file_size,
        "content_type": row.content_type,
        "uploaded_by": row.uploaded_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _resource_to_target_type(resource: str) -> str | None:
    return {"guests": "guest", "reservations": "reservation", "properties": "property"}.get(
        resource
    )


@api_bp.get("/search")
@require_api_key
@scope_required("search:read")
def api_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return json_ok([])
    ilike = f"%{q}%"
    org_id = _org_id()
    data: list[dict] = []

    guests = (
        Guest.query.filter(
            Guest.organization_id == org_id,
            (
                Guest.first_name.ilike(ilike)
                | Guest.last_name.ilike(ilike)
                | Guest.email.ilike(ilike)
                | Guest.phone.ilike(ilike)
            ),
        )
        .order_by(Guest.id.desc())
        .limit(20)
        .all()
    )
    for row in guests:
        data.append(
            {
                "type": "guest",
                "id": row.id,
                "label": row.full_name or f"Guest #{row.id}",
                "sublabel": row.email or row.phone or "",
                "url": f"/admin/guests/{row.id}",
            }
        )

    reservations = (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == org_id,
            (Reservation.guest_name.ilike(ilike)),
        )
        .order_by(Reservation.id.desc())
        .limit(20)
        .all()
    )
    for row in reservations:
        data.append(
            {
                "type": "reservation",
                "id": row.id,
                "label": f"Reservation #{row.id}",
                "sublabel": row.guest_name or "",
                "url": f"/admin/reservations/{row.id}",
            }
        )

    properties = (
        Property.query.filter(
            Property.organization_id == org_id,
            (
                Property.name.ilike(ilike)
                | Property.address.ilike(ilike)
                | Property.city.ilike(ilike)
                | Property.street_address.ilike(ilike)
                | Property.postal_code.ilike(ilike)
            ),
        )
        .order_by(Property.id.desc())
        .limit(20)
        .all()
    )
    for row in properties:
        data.append(
            {
                "type": "property",
                "id": row.id,
                "label": row.name,
                "sublabel": row.street_address or row.address or row.city or "",
                "url": f"/admin/properties/{row.id}",
            }
        )

    guest_tag_matches = (
        Guest.query.join(GuestTag, GuestTag.guest_id == Guest.id)
        .join(Tag, Tag.id == GuestTag.tag_id)
        .filter(Guest.organization_id == org_id, Tag.name.ilike(ilike))
        .order_by(Guest.id.desc())
        .limit(20)
        .all()
    )
    seen = {(x["type"], x["id"]) for x in data}
    for row in guest_tag_matches:
        key = ("guest", row.id)
        if key in seen:
            continue
        data.append(
            {
                "type": "guest",
                "id": row.id,
                "label": row.full_name or f"Guest #{row.id}",
                "sublabel": row.email or row.phone or "",
                "url": f"/admin/guests/{row.id}",
            }
        )
        seen.add(key)

    reservation_tag_matches = (
        Reservation.query.join(ReservationTag, ReservationTag.reservation_id == Reservation.id)
        .join(Tag, Tag.id == ReservationTag.tag_id)
        .join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == org_id, Tag.name.ilike(ilike))
        .order_by(Reservation.id.desc())
        .limit(20)
        .all()
    )
    for row in reservation_tag_matches:
        key = ("reservation", row.id)
        if key in seen:
            continue
        data.append(
            {
                "type": "reservation",
                "id": row.id,
                "label": f"Reservation #{row.id}",
                "sublabel": row.guest_name or "",
                "url": f"/admin/reservations/{row.id}",
            }
        )
        seen.add(key)

    property_tag_matches = (
        Property.query.join(PropertyTag, PropertyTag.property_id == Property.id)
        .join(Tag, Tag.id == PropertyTag.tag_id)
        .filter(Property.organization_id == org_id, Tag.name.ilike(ilike))
        .order_by(Property.id.desc())
        .limit(20)
        .all()
    )
    for row in property_tag_matches:
        key = ("property", row.id)
        if key in seen:
            continue
        data.append(
            {
                "type": "property",
                "id": row.id,
                "label": row.name,
                "sublabel": row.street_address or row.address or row.city or "",
                "url": f"/admin/properties/{row.id}",
            }
        )
        seen.add(key)

    invoices = (
        Invoice.query.filter(Invoice.organization_id == org_id, Invoice.invoice_number.ilike(ilike))
        .order_by(Invoice.id.desc())
        .limit(20)
        .all()
    )
    for row in invoices:
        data.append(
            {
                "type": "invoice",
                "id": row.id,
                "label": row.invoice_number or f"Invoice #{row.id}",
                "sublabel": row.status or "",
                "url": f"/admin/invoices/{row.id}",
            }
        )
    return json_ok(data[:20])


@api_bp.get("/tags")
@require_api_key
@scope_required("tags:read")
def list_tags():
    rows = TagService.list_for_org(_org_id())
    return json_ok([_serialize_tag(row) for row in rows])


@api_bp.post("/tags")
@require_api_key
@scope_required("tags:write")
def create_tag():
    payload = _payload()
    try:
        row = TagService.create(
            organization_id=_org_id(),
            name=str(payload.get("name", "")),
            color=str(payload.get("color", "")),
            created_by_user_id=_actor_user_id() or g.api_key.user_id or 0,
        )
        db.session.commit()
    except TagServiceError as err:
        db.session.rollback()
        return json_error(err.code, err.message, status=err.status)
    return json_ok(_serialize_tag(row), status=201)


@api_bp.post("/<string:resource>/<int:resource_id>/tags")
@require_api_key
@scope_required("admin:*")
def attach_tag(resource: str, resource_id: int):
    required_scope = f"{resource}:write"
    if not any(
        s == required_scope or s == "admin:*" or s == resource.replace("s", "") + ":*"
        for s in g.api_key.scope_list
    ):
        return json_error("forbidden", f"Missing required scope: {required_scope}", status=403)
    target_type = _resource_to_target_type(resource)
    if target_type is None:
        return json_error("not_found", "Resource not supported.", status=404)
    payload = _payload()
    try:
        tag_id = int(payload.get("tag_id", 0))
        TagService.attach(
            organization_id=_org_id(),
            target_type=target_type,
            target_id=resource_id,
            tag_id=tag_id,
            actor_user_id=_actor_user_id() or g.api_key.user_id or 0,
        )
        db.session.commit()
    except (TypeError, ValueError):
        return json_error("validation_error", "tag_id must be an integer.", status=400)
    except TagServiceError as err:
        db.session.rollback()
        return json_error(err.code, err.message, status=err.status)
    return json_ok({"ok": True})


@api_bp.delete("/<string:resource>/<int:resource_id>/tags/<int:tag_id>")
@require_api_key
@scope_required("admin:*")
def detach_tag(resource: str, resource_id: int, tag_id: int):
    required_scope = f"{resource}:write"
    if required_scope not in g.api_key.scope_list and "admin:*" not in g.api_key.scope_list:
        return json_error("forbidden", f"Missing required scope: {required_scope}", status=403)
    target_type = _resource_to_target_type(resource)
    if target_type is None:
        return json_error("not_found", "Resource not supported.", status=404)
    try:
        TagService.detach(
            organization_id=_org_id(),
            target_type=target_type,
            target_id=resource_id,
            tag_id=tag_id,
            actor_user_id=_actor_user_id() or g.api_key.user_id or 0,
        )
        db.session.commit()
    except TagServiceError as err:
        db.session.rollback()
        return json_error(err.code, err.message, status=err.status)
    return json_ok({"ok": True})


@api_bp.get("/<string:resource>/<int:resource_id>/comments")
@require_api_key
@scope_required("admin:*")
def list_comments(resource: str, resource_id: int):
    target_type = _resource_to_target_type(resource)
    if target_type is None:
        return json_error("not_found", "Resource not supported.", status=404)
    try:
        rows = CommentService.list_for_target(
            organization_id=_org_id(),
            target_type=target_type,
            target_id=resource_id,
            include_internal=True,
        )
    except CommentServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok([_serialize_comment(row) for row in rows])


@api_bp.post("/<string:resource>/<int:resource_id>/comments")
@require_api_key
@scope_required("admin:*")
def create_comment(resource: str, resource_id: int):
    target_type = _resource_to_target_type(resource)
    if target_type is None:
        return json_error("not_found", "Resource not supported.", status=404)
    payload = _payload()
    try:
        row = CommentService.create(
            organization_id=_org_id(),
            target_type=target_type,
            target_id=resource_id,
            author_user_id=_actor_user_id() or g.api_key.user_id or 0,
            body=str(payload.get("body", "")),
            is_internal=bool(payload.get("is_internal", True)),
        )
        db.session.commit()
    except CommentServiceError as err:
        db.session.rollback()
        return json_error(err.code, err.message, status=err.status)
    return json_ok(_serialize_comment(row), status=201)


@api_bp.patch("/comments/<int:comment_id>")
@require_api_key
@scope_required("admin:*")
def edit_comment(comment_id: int):
    payload = _payload()
    try:
        row = CommentService.edit(
            comment_id=comment_id,
            actor_user_id=_actor_user_id() or g.api_key.user_id or 0,
            body=str(payload.get("body", "")),
        )
        db.session.commit()
    except CommentServiceError as err:
        db.session.rollback()
        return json_error(err.code, err.message, status=err.status)
    return json_ok(_serialize_comment(row))


@api_bp.delete("/comments/<int:comment_id>")
@require_api_key
@scope_required("admin:*")
def delete_comment(comment_id: int):
    try:
        CommentService.delete(
            comment_id=comment_id,
            actor_user_id=_actor_user_id() or g.api_key.user_id or 0,
        )
        db.session.commit()
    except CommentServiceError as err:
        db.session.rollback()
        return json_error(err.code, err.message, status=err.status)
    return json_ok({"ok": True})


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
            city=payload.get("city"),
            postal_code=payload.get("postal_code"),
            street_address=payload.get("street_address"),
            latitude=payload.get("latitude"),
            longitude=payload.get("longitude"),
            year_built=payload.get("year_built"),
            has_elevator=bool(payload.get("has_elevator", False)),
            has_parking=bool(payload.get("has_parking", False)),
            has_sauna=bool(payload.get("has_sauna", False)),
            has_courtyard=bool(payload.get("has_courtyard", False)),
            has_air_conditioning=bool(payload.get("has_air_conditioning", False)),
            description=payload.get("description"),
            url=payload.get("url"),
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
            floor=payload.get("floor"),
            area_sqm=payload.get("area_sqm"),
            bedrooms=int(payload.get("bedrooms", 0)),
            has_kitchen=bool(payload.get("has_kitchen", False)),
            has_bathroom=bool(payload.get("has_bathroom", True)),
            has_balcony=bool(payload.get("has_balcony", False)),
            has_terrace=bool(payload.get("has_terrace", False)),
            has_dishwasher=bool(payload.get("has_dishwasher", False)),
            has_washing_machine=bool(payload.get("has_washing_machine", False)),
            has_tv=bool(payload.get("has_tv", False)),
            has_wifi=bool(payload.get("has_wifi", True)),
            max_guests=int(payload.get("max_guests", 2)),
            description=payload.get("description"),
            floor_plan_image_id=payload.get("floor_plan_image_id"),
            actor_user_id=_actor_user_id(),
        )
    except property_service.PropertyServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(data, status=201)


@api_bp.get("/properties/<int:property_id>/images")
@require_api_key
@scope_required("properties:read")
def list_property_images_api(property_id: int):
    try:
        rows = property_image_service.list_property_images(
            organization_id=_org_id(),
            property_id=property_id,
        )
    except property_image_service.PropertyImageError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok([_serialize_property_image(row) for row in rows])


@api_bp.post("/properties/<int:property_id>/images")
@require_api_key
@scope_required("properties:write")
def upload_property_image_api(property_id: int):
    file = request.files.get("image")
    alt_text = (request.form.get("alt_text") or "").strip()
    if file is None or not file.filename:
        return json_error("validation_error", "Field 'image' is required.", status=400)
    try:
        row = property_image_service.upload_property_image(
            organization_id=_org_id(),
            property_id=property_id,
            raw=file.read(),
            content_type=(file.mimetype or "").lower(),
            alt_text=alt_text,
            uploaded_by=_actor_user_id() or g.api_key.user_id,
        )
    except property_image_service.PropertyImageError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(_serialize_property_image(row), status=201)


@api_bp.delete("/properties/<int:property_id>/images/<int:image_id>")
@require_api_key
@scope_required("properties:write")
def delete_property_image_api(property_id: int, image_id: int):
    try:
        property_image_service.delete_property_image(
            organization_id=_org_id(),
            property_id=property_id,
            image_id=image_id,
        )
    except property_image_service.PropertyImageError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok({"ok": True})


@api_bp.post("/properties/<int:property_id>/images/reorder")
@require_api_key
@scope_required("properties:write")
def reorder_property_images_api(property_id: int):
    payload = _payload()
    raw_ids = payload.get("ids")
    if not isinstance(raw_ids, list):
        return json_error("validation_error", "Field 'ids' must be an array.", status=400)
    try:
        ids = [int(x) for x in raw_ids]
        property_image_service.reorder_property_images(
            organization_id=_org_id(),
            property_id=property_id,
            ids=ids,
        )
    except ValueError:
        return json_error("validation_error", "Field 'ids' must contain integer IDs.", status=400)
    except property_image_service.PropertyImageError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok({"ok": True})


@api_bp.get("/property-images/<path:key>")
@require_api_key
@scope_required("properties:read")
def serve_property_image_local(key: str):
    if (current_app.config.get("STORAGE_BACKEND") or "local").strip().lower() != "local":
        return json_error("not_found", "Not found.", status=404)
    from app.storage.local import LocalStorage

    storage = LocalStorage()
    path = storage.path_for_key(key=key)
    if not path.exists() or not path.is_file():
        return json_error("not_found", "Not found.", status=404)
    return send_file(path)


@api_bp.get("/units/<int:unit_id>/calendar.ics")
@scope_required("properties:read")
def export_unit_calendar_ics(unit_id: int):
    api_key = getattr(g, "api_key", None)
    if api_key is not None:
        row = get_unit_for_org_calendar_export(
            organization_id=api_key.organization_id,
            unit_id=unit_id,
        )
        if row is None:
            return json_error("not_found", "Unit not found.", status=404)
    service = IcalService()
    try:
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
        sub_raw = payload.get("subtotal_excl_vat")
        if sub_raw is None or str(sub_raw).strip() == "":
            sub_raw = payload.get("amount")
        vat_raw = payload.get("vat_rate")
        if lid is not None:
            data = billing_service.create_invoice_for_lease(
                organization_id=_org_id(),
                lease_id=lid,
                subtotal_excl_vat_raw=sub_raw,
                due_date_raw=str(payload.get("due_date", "")),
                currency=str(payload.get("currency")) if payload.get("currency") else None,
                description=str(payload.get("description")) if payload.get("description") else None,
                status=str(payload.get("status", "open")),
                actor_user_id=actor,
                vat_rate_raw=vat_raw,
            )
        else:
            res_raw = payload.get("reservation_id")
            guest_raw = payload.get("guest_id")
            data = billing_service.create_invoice(
                organization_id=_org_id(),
                subtotal_excl_vat_raw=sub_raw,
                due_date_raw=str(payload.get("due_date", "")),
                currency=str(payload.get("currency")) if payload.get("currency") else None,
                description=str(payload.get("description")) if payload.get("description") else None,
                lease_id=None,
                reservation_id=int(res_raw) if res_raw not in (None, "") else None,
                guest_id=int(guest_raw) if guest_raw not in (None, "") else None,
                status=str(payload.get("status", "draft")),
                metadata_json=payload.get("metadata_json"),
                actor_user_id=actor,
                vat_rate_raw=vat_raw,
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


@api_bp.get("/invoices/<int:invoice_id>/pdf")
@require_api_key
@scope_required("invoices:read")
@require_api_tenant_entity(Invoice, id_param="invoice_id")
def api_invoice_pdf(invoice_id: int):
    inv = g.scoped_entity
    try:
        pdf_bytes = generate_invoice_pdf(invoice_id)
    except billing_service.InvoiceServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    billing_service.log_invoice_pdf_downloaded(
        invoice_id=invoice_id,
        organization_id=inv.organization_id,
    )
    safe_name = (inv.invoice_number or f"INV-{inv.id}").replace("/", "-").replace("\\", "-")
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"lasku-{safe_name}.pdf",
    )


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


def _webhook_subscription_dict(row) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "url": row.url,
        "events": row.events if isinstance(row.events, list) else [],
        "is_active": row.is_active,
        "failure_count": row.failure_count,
        "last_delivery_at": row.last_delivery_at.isoformat() if row.last_delivery_at else None,
        "last_delivery_status": row.last_delivery_status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@api_bp.get("/webhooks/subscriptions")
@require_api_key
@scope_required("webhooks:read")
def list_webhook_subscriptions_api():
    from app.webhooks.services import list_subscriptions_for_org

    rows = list_subscriptions_for_org(organization_id=_org_id())
    audit_record(
        "webhook.subscriptions_listed",
        status=AuditStatus.SUCCESS,
        organization_id=_org_id(),
        target_type="webhook_subscription",
        target_id=None,
        metadata={"count": len(rows)},
        commit=True,
    )
    return json_ok([_webhook_subscription_dict(r) for r in rows])


@api_bp.post("/webhooks/subscriptions")
@require_api_key
@scope_required("webhooks:write")
def create_webhook_subscription_api():
    from app.webhooks.services import create_outbound_subscription

    body = _payload()
    url = str(body.get("url") or "").strip()
    events_raw = body.get("events")
    if not url:
        return json_error("validation_error", "Field 'url' is required.", status=400)
    if not isinstance(events_raw, list) or not events_raw:
        return json_error(
            "validation_error",
            "Field 'events' must be a non-empty JSON array of strings.",
            status=400,
        )
    events = [str(x).strip() for x in events_raw if str(x).strip()]
    if not events:
        return json_error(
            "validation_error",
            "Field 'events' must contain at least one non-empty string.",
            status=400,
        )
    sub, raw_secret = create_outbound_subscription(
        organization_id=_org_id(),
        url=url,
        events=events,
        created_by_user_id=_actor_user_id(),
    )
    audit_record(
        "webhook.subscription_created",
        status=AuditStatus.SUCCESS,
        organization_id=_org_id(),
        target_type="webhook_subscription",
        target_id=sub.id,
        metadata={"url": url, "events": events},
        commit=True,
    )
    data = _webhook_subscription_dict(sub)
    data["secret"] = raw_secret
    return json_ok(data, status=201)


@api_bp.delete("/webhooks/subscriptions/<int:subscription_id>")
@require_api_key
@scope_required("webhooks:write")
def delete_webhook_subscription_api(subscription_id: int):
    from app.webhooks.services import deactivate_outbound_subscription

    ok = deactivate_outbound_subscription(
        subscription_id=subscription_id,
        organization_id=_org_id(),
    )
    if not ok:
        return json_error("not_found", "Subscription not found.", status=404)
    audit_record(
        "webhook.subscription_deactivated",
        status=AuditStatus.SUCCESS,
        organization_id=_org_id(),
        target_type="webhook_subscription",
        target_id=subscription_id,
        commit=True,
    )
    return json_ok({"id": subscription_id, "is_active": False})
