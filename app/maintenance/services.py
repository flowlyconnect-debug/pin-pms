"""Tenant-scoped maintenance request business logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.extensions import db
from app.guests.models import Guest
from app.maintenance.models import MaintenanceRequest
from app.notifications import services as notification_service
from app.properties.models import Property, Unit
from app.reservations.models import Reservation
from app.users.models import User
from app.webhooks.events import MAINTENANCE_REQUESTED
from app.webhooks.publisher import publish as publish_webhook_event
from app.webhooks.schemas import build_maintenance_requested_payload


@dataclass
class MaintenanceServiceError(Exception):
    code: str
    message: str
    status: int


_STATUSES = frozenset({"new", "in_progress", "waiting", "resolved", "cancelled"})
_OPEN_STATUSES = frozenset({"new", "in_progress", "waiting"})
_PRIORITIES = frozenset({"low", "normal", "high", "urgent"})


def _parse_optional_date(raw: str | None, field_name: str) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise MaintenanceServiceError(
            code="validation_error",
            message=f"Field '{field_name}' must be a valid ISO date (YYYY-MM-DD).",
            status=400,
        ) from exc


def _scoped_property(*, organization_id: int, property_id: int) -> Property | None:
    return Property.query.filter_by(id=property_id, organization_id=organization_id).first()


def _scoped_unit_on_property(
    *, organization_id: int, property_id: int, unit_id: int
) -> Unit | None:
    return (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(
            Unit.id == unit_id,
            Property.organization_id == organization_id,
            Property.id == property_id,
        )
        .first()
    )


def _scoped_guest(*, organization_id: int, guest_id: int) -> Guest | None:
    return Guest.query.filter_by(id=guest_id, organization_id=organization_id).first()


def _scoped_reservation(*, organization_id: int, reservation_id: int) -> Reservation | None:
    return (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Reservation.id == reservation_id,
            Property.organization_id == organization_id,
        )
        .first()
    )


def _scoped_user(*, organization_id: int, user_id: int) -> User | None:
    return User.query.filter_by(id=user_id, organization_id=organization_id, is_active=True).first()


def _get_row(*, organization_id: int, request_id: int) -> MaintenanceRequest | None:
    return MaintenanceRequest.query.filter_by(
        id=request_id,
        organization_id=organization_id,
    ).first()


def _serialize(row: MaintenanceRequest) -> dict[str, Any]:
    prop = row.property
    unit = row.unit
    guest = row.guest
    assignee = row.assigned_to
    creator = row.created_by
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "property_id": row.property_id,
        "property_name": prop.name if prop is not None else None,
        "unit_id": row.unit_id,
        "unit_name": unit.name if unit is not None else None,
        "guest_id": row.guest_id,
        "guest_name": guest.full_name if guest is not None else None,
        "reservation_id": row.reservation_id,
        "title": row.title,
        "description": row.description,
        "status": row.status,
        "priority": row.priority,
        "assigned_to_id": row.assigned_to_id,
        "assigned_to_email": assignee.email if assignee is not None else None,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "created_by_id": row.created_by_id,
        "created_by_email": creator.email if creator is not None else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_maintenance_requests_paginated(
    *,
    organization_id: int,
    page: int,
    per_page: int,
    status: str | None = None,
    priority: str | None = None,
    property_id: int | None = None,
    unit_id: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    q = MaintenanceRequest.query.filter_by(organization_id=organization_id)
    if status:
        q = q.filter(MaintenanceRequest.status == status.strip().lower())
    if priority:
        q = q.filter(MaintenanceRequest.priority == priority.strip().lower())
    if property_id is not None:
        q = q.filter(MaintenanceRequest.property_id == property_id)
    if unit_id is not None:
        q = q.filter(MaintenanceRequest.unit_id == unit_id)
    total = q.count()
    rows = (
        q.order_by(MaintenanceRequest.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    )
    return [_serialize(r) for r in rows], total


def get_maintenance_request(*, organization_id: int, request_id: int) -> dict[str, Any]:
    row = _get_row(organization_id=organization_id, request_id=request_id)
    if row is None:
        raise MaintenanceServiceError(
            code="not_found",
            message="Maintenance request not found.",
            status=404,
        )
    return _serialize(row)


def create_maintenance_request(
    *,
    organization_id: int,
    property_id: int,
    unit_id: int | None,
    guest_id: int | None,
    reservation_id: int | None,
    title: str,
    description: str | None,
    priority: str,
    status: str,
    due_date_raw: str | None,
    assigned_to_id: int | None,
    actor_user_id: int,
) -> dict[str, Any]:
    title_clean = (title or "").strip()
    if not title_clean:
        raise MaintenanceServiceError(
            code="validation_error",
            message="Title is required.",
            status=400,
        )

    if _scoped_property(organization_id=organization_id, property_id=property_id) is None:
        raise MaintenanceServiceError(
            code="validation_error",
            message="Property not found in this organization.",
            status=400,
        )

    unit_id_clean = unit_id
    if unit_id_clean is not None:
        if (
            _scoped_unit_on_property(
                organization_id=organization_id,
                property_id=property_id,
                unit_id=unit_id_clean,
            )
            is None
        ):
            raise MaintenanceServiceError(
                code="validation_error",
                message="Unit not found for this property.",
                status=400,
            )

    if (
        guest_id is not None
        and _scoped_guest(organization_id=organization_id, guest_id=guest_id) is None
    ):
        raise MaintenanceServiceError(
            code="validation_error",
            message="Guest not found in this organization.",
            status=400,
        )

    if reservation_id is not None:
        if (
            _scoped_reservation(organization_id=organization_id, reservation_id=reservation_id)
            is None
        ):
            raise MaintenanceServiceError(
                code="validation_error",
                message="Reservation not found in this organization.",
                status=400,
            )

    st = (status or "new").strip().lower()
    if st not in _STATUSES or st in {"resolved", "cancelled"}:
        raise MaintenanceServiceError(
            code="validation_error",
            message="Initial status must be new, in_progress, or waiting.",
            status=400,
        )

    pr = (priority or "normal").strip().lower()
    if pr not in _PRIORITIES:
        raise MaintenanceServiceError(
            code="validation_error",
            message="priority must be one of: low, normal, high, urgent.",
            status=400,
        )

    due = _parse_optional_date(due_date_raw, "due_date")

    assignee_id = assigned_to_id
    if assignee_id is not None:
        if _scoped_user(organization_id=organization_id, user_id=assignee_id) is None:
            raise MaintenanceServiceError(
                code="validation_error",
                message="Assignee must be an active user in this organization.",
                status=400,
            )

    row = MaintenanceRequest(
        organization_id=organization_id,
        property_id=property_id,
        unit_id=unit_id_clean,
        guest_id=guest_id,
        reservation_id=reservation_id,
        title=title_clean,
        description=(description or "").strip() or None,
        status=st,
        priority=pr,
        assigned_to_id=assignee_id,
        due_date=due,
        resolved_at=None,
        created_by_id=actor_user_id,
    )
    db.session.add(row)
    db.session.flush()

    audit_record(
        "maintenance_request.created",
        status=AuditStatus.SUCCESS,
        organization_id=organization_id,
        target_type="maintenance_request",
        target_id=row.id,
        context={
            "title": row.title,
            "status": row.status,
            "priority": row.priority,
            "property_id": row.property_id,
            "unit_id": row.unit_id,
        },
    )
    notification_service.create(
        organization_id=organization_id,
        type="maintenance.requested",
        title="Uusi huoltopyynto",
        body=row.title,
        link=f"/admin/maintenance-requests/{row.id}",
        severity="warning" if row.priority in {"high", "urgent"} else "info",
    )
    db.session.commit()
    publish_webhook_event(
        MAINTENANCE_REQUESTED,
        organization_id,
        build_maintenance_requested_payload(row),
    )
    return _serialize(row)


def update_maintenance_request(
    *,
    organization_id: int,
    request_id: int,
    data: Mapping[str, Any],
    actor_user_id: int,
) -> dict[str, Any]:
    row = _get_row(organization_id=organization_id, request_id=request_id)
    if row is None:
        raise MaintenanceServiceError(
            code="not_found",
            message="Maintenance request not found.",
            status=404,
        )
    if row.status in {"resolved", "cancelled"}:
        raise MaintenanceServiceError(
            code="validation_error",
            message="Cannot edit a resolved or cancelled maintenance request.",
            status=400,
        )

    old_status = row.status
    old_assignee = row.assigned_to_id

    if "title" in data:
        t = str(data["title"] or "").strip()
        if not t:
            raise MaintenanceServiceError(
                code="validation_error",
                message="Title cannot be empty.",
                status=400,
            )
        row.title = t

    if "description" in data:
        row.description = str(data["description"] or "").strip() or None

    if "priority" in data:
        pr = str(data["priority"] or "").strip().lower()
        if pr not in _PRIORITIES:
            raise MaintenanceServiceError(
                code="validation_error",
                message="priority must be one of: low, normal, high, urgent.",
                status=400,
            )
        row.priority = pr

    if "status" in data:
        st = str(data["status"] or "").strip().lower()
        if st not in _OPEN_STATUSES:
            raise MaintenanceServiceError(
                code="validation_error",
                message="Use resolve or cancel actions for terminal statuses.",
                status=400,
            )
        if st != old_status:
            row.status = st
            audit_record(
                "maintenance_request.status_changed",
                status=AuditStatus.SUCCESS,
                organization_id=organization_id,
                target_type="maintenance_request",
                target_id=row.id,
                context={"from_status": old_status, "to_status": st},
            )

    if "property_id" in data:
        pid = int(data["property_id"])
        if _scoped_property(organization_id=organization_id, property_id=pid) is None:
            raise MaintenanceServiceError(
                code="validation_error",
                message="Property not found in this organization.",
                status=400,
            )
        row.property_id = pid
        if row.unit_id is not None:
            if (
                _scoped_unit_on_property(
                    organization_id=organization_id,
                    property_id=pid,
                    unit_id=row.unit_id,
                )
                is None
            ):
                row.unit_id = None

    if "unit_id" in data:
        uid = data["unit_id"]
        if uid in (None, ""):
            row.unit_id = None
        else:
            uid_int = int(uid)
            if (
                _scoped_unit_on_property(
                    organization_id=organization_id,
                    property_id=row.property_id,
                    unit_id=uid_int,
                )
                is None
            ):
                raise MaintenanceServiceError(
                    code="validation_error",
                    message="Unit not found for this property.",
                    status=400,
                )
            row.unit_id = uid_int

    if "guest_id" in data:
        gid = data["guest_id"]
        if gid in (None, ""):
            row.guest_id = None
        else:
            gid_int = int(gid)
            if _scoped_guest(organization_id=organization_id, guest_id=gid_int) is None:
                raise MaintenanceServiceError(
                    code="validation_error",
                    message="Guest not found in this organization.",
                    status=400,
                )
            row.guest_id = gid_int

    if "reservation_id" in data:
        rid = data["reservation_id"]
        if rid in (None, ""):
            row.reservation_id = None
        else:
            rid_int = int(rid)
            if _scoped_reservation(organization_id=organization_id, reservation_id=rid_int) is None:
                raise MaintenanceServiceError(
                    code="validation_error",
                    message="Reservation not found in this organization.",
                    status=400,
                )
            row.reservation_id = rid_int

    if "due_date" in data:
        raw = data["due_date"]
        if raw in (None, ""):
            row.due_date = None
        else:
            row.due_date = _parse_optional_date(str(raw), "due_date")

    if "assigned_to_id" in data:
        aid = data["assigned_to_id"]
        if aid in (None, ""):
            row.assigned_to_id = None
        else:
            aid_int = int(aid)
            if _scoped_user(organization_id=organization_id, user_id=aid_int) is None:
                raise MaintenanceServiceError(
                    code="validation_error",
                    message="Assignee must be an active user in this organization.",
                    status=400,
                )
            row.assigned_to_id = aid_int
        if row.assigned_to_id != old_assignee:
            audit_record(
                "maintenance_request.assigned",
                status=AuditStatus.SUCCESS,
                organization_id=organization_id,
                target_type="maintenance_request",
                target_id=row.id,
                context={
                    "from_user_id": old_assignee,
                    "to_user_id": row.assigned_to_id,
                },
            )

    db.session.commit()
    return _serialize(row)


def resolve_maintenance_request(
    *,
    organization_id: int,
    request_id: int,
    actor_user_id: int,
) -> dict[str, Any]:
    _ = actor_user_id
    row = _get_row(organization_id=organization_id, request_id=request_id)
    if row is None:
        raise MaintenanceServiceError(
            code="not_found",
            message="Maintenance request not found.",
            status=404,
        )
    if row.status == "resolved":
        raise MaintenanceServiceError(
            code="validation_error",
            message="Request is already resolved.",
            status=400,
        )
    if row.status == "cancelled":
        raise MaintenanceServiceError(
            code="validation_error",
            message="Cannot resolve a cancelled request.",
            status=400,
        )
    row.status = "resolved"
    row.resolved_at = datetime.now(timezone.utc)
    audit_record(
        "maintenance_request.resolved",
        status=AuditStatus.SUCCESS,
        organization_id=organization_id,
        target_type="maintenance_request",
        target_id=row.id,
        context={"resolved_at": row.resolved_at.isoformat()},
    )
    db.session.commit()
    return _serialize(row)


def cancel_maintenance_request(
    *,
    organization_id: int,
    request_id: int,
    actor_user_id: int,
) -> dict[str, Any]:
    _ = actor_user_id
    row = _get_row(organization_id=organization_id, request_id=request_id)
    if row is None:
        raise MaintenanceServiceError(
            code="not_found",
            message="Maintenance request not found.",
            status=404,
        )
    if row.status == "resolved":
        raise MaintenanceServiceError(
            code="validation_error",
            message="Cannot cancel a resolved request.",
            status=400,
        )
    if row.status == "cancelled":
        raise MaintenanceServiceError(
            code="validation_error",
            message="Request is already cancelled.",
            status=400,
        )
    row.status = "cancelled"
    audit_record(
        "maintenance_request.cancelled",
        status=AuditStatus.SUCCESS,
        organization_id=organization_id,
        target_type="maintenance_request",
        target_id=row.id,
        context={},
    )
    db.session.commit()
    return _serialize(row)
