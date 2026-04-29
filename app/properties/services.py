from __future__ import annotations

from dataclasses import dataclass

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.extensions import db
from app.properties.models import Property, Unit


@dataclass
class PropertyServiceError(Exception):
    code: str
    message: str
    status: int


def _serialize_property(row: Property) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "name": row.name,
        "address": row.address,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_unit(row: Unit) -> dict:
    return {
        "id": row.id,
        "property_id": row.property_id,
        "name": row.name,
        "unit_type": row.unit_type,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_properties(*, organization_id: int) -> list[dict]:
    rows = (
        Property.query.filter_by(organization_id=organization_id).order_by(Property.id.asc()).all()
    )
    return [_serialize_property(row) for row in rows]


def list_properties_paginated(
    *,
    organization_id: int,
    page: int,
    per_page: int,
) -> tuple[list[dict], int]:
    query = Property.query.filter_by(organization_id=organization_id)
    total = query.count()
    rows = query.order_by(Property.id.asc()).offset((page - 1) * per_page).limit(per_page).all()
    return [_serialize_property(row) for row in rows], total


def create_property(
    *,
    organization_id: int,
    name: str,
    address: str | None,
    actor_user_id: int | None = None,
) -> dict:
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise PropertyServiceError(
            code="validation_error",
            message="Field 'name' is required.",
            status=400,
        )

    row = Property(
        organization_id=organization_id,
        name=normalized_name,
        address=(address or "").strip() or None,
    )
    db.session.add(row)
    db.session.commit()
    audit_record(
        "property_created",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="property",
        target_id=row.id,
        context={"user_id": actor_user_id} if actor_user_id is not None else None,
        commit=True,
    )
    return _serialize_property(row)


def get_property(*, organization_id: int, property_id: int) -> dict:
    row = Property.query.filter_by(id=property_id, organization_id=organization_id).first()
    if row is None:
        raise PropertyServiceError(
            code="not_found",
            message="Property not found.",
            status=404,
        )
    return _serialize_property(row)


def update_property(
    *,
    organization_id: int,
    property_id: int,
    name: str,
    address: str | None,
    actor_user_id: int | None = None,
) -> dict:
    row = Property.query.filter_by(id=property_id, organization_id=organization_id).first()
    if row is None:
        raise PropertyServiceError(
            code="not_found",
            message="Property not found.",
            status=404,
        )

    normalized_name = (name or "").strip()
    if not normalized_name:
        raise PropertyServiceError(
            code="validation_error",
            message="Field 'name' is required.",
            status=400,
        )

    row.name = normalized_name
    row.address = (address or "").strip() or None
    db.session.commit()
    audit_record(
        "property_updated",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="property",
        target_id=row.id,
        context={"user_id": actor_user_id} if actor_user_id is not None else None,
        commit=True,
    )
    return _serialize_property(row)


def list_units(*, organization_id: int, property_id: int) -> list[dict]:
    _ = get_property(organization_id=organization_id, property_id=property_id)
    rows = Unit.query.filter_by(property_id=property_id).order_by(Unit.id.asc()).all()
    return [_serialize_unit(row) for row in rows]


def get_unit(*, organization_id: int, unit_id: int) -> dict:
    row = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Unit.id == unit_id, Property.organization_id == organization_id)
        .first()
    )
    if row is None:
        raise PropertyServiceError(
            code="not_found",
            message="Unit not found.",
            status=404,
        )
    return _serialize_unit(row)


def create_unit(
    *,
    organization_id: int,
    property_id: int,
    name: str,
    unit_type: str | None,
    actor_user_id: int | None = None,
) -> dict:
    _ = get_property(organization_id=organization_id, property_id=property_id)

    normalized_name = (name or "").strip()
    if not normalized_name:
        raise PropertyServiceError(
            code="validation_error",
            message="Field 'name' is required.",
            status=400,
        )

    row = Unit(
        property_id=property_id,
        name=normalized_name,
        unit_type=(unit_type or "").strip() or None,
    )
    db.session.add(row)
    db.session.commit()
    audit_record(
        "unit_created",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="unit",
        target_id=row.id,
        context=(
            {"property_id": property_id, "user_id": actor_user_id}
            if actor_user_id is not None
            else {"property_id": property_id}
        ),
        commit=True,
    )
    return _serialize_unit(row)


def update_unit(
    *,
    organization_id: int,
    unit_id: int,
    name: str,
    unit_type: str | None,
    actor_user_id: int | None = None,
) -> dict:
    row = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Unit.id == unit_id, Property.organization_id == organization_id)
        .first()
    )
    if row is None:
        raise PropertyServiceError(
            code="not_found",
            message="Unit not found.",
            status=404,
        )

    normalized_name = (name or "").strip()
    if not normalized_name:
        raise PropertyServiceError(
            code="validation_error",
            message="Field 'name' is required.",
            status=400,
        )

    row.name = normalized_name
    row.unit_type = (unit_type or "").strip() or None
    db.session.commit()
    audit_record(
        "unit_updated",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="unit",
        target_id=row.id,
        context=(
            {"property_id": row.property_id, "user_id": actor_user_id}
            if actor_user_id is not None
            else {"property_id": row.property_id}
        ),
        commit=True,
    )
    return _serialize_unit(row)
