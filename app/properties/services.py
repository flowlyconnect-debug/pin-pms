from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

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
        "city": row.city,
        "postal_code": row.postal_code,
        "street_address": row.street_address,
        "latitude": str(row.latitude) if row.latitude is not None else None,
        "longitude": str(row.longitude) if row.longitude is not None else None,
        "year_built": row.year_built,
        "has_elevator": row.has_elevator,
        "has_parking": row.has_parking,
        "has_sauna": row.has_sauna,
        "has_courtyard": row.has_courtyard,
        "description": row.description,
        "url": row.url,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_unit(row: Unit) -> dict:
    return {
        "id": row.id,
        "property_id": row.property_id,
        "name": row.name,
        "unit_type": row.unit_type,
        "floor": row.floor,
        "area_sqm": str(row.area_sqm) if row.area_sqm is not None else None,
        "bedrooms": row.bedrooms,
        "has_kitchen": row.has_kitchen,
        "has_bathroom": row.has_bathroom,
        "has_balcony": row.has_balcony,
        "has_terrace": row.has_terrace,
        "has_dishwasher": row.has_dishwasher,
        "has_washing_machine": row.has_washing_machine,
        "has_tv": row.has_tv,
        "has_wifi": row.has_wifi,
        "max_guests": row.max_guests,
        "description": row.description,
        "floor_plan_image_id": row.floor_plan_image_id,
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
    city: str | None = None,
    postal_code: str | None = None,
    street_address: str | None = None,
    latitude: Decimal | None = None,
    longitude: Decimal | None = None,
    year_built: int | None = None,
    has_elevator: bool = False,
    has_parking: bool = False,
    has_sauna: bool = False,
    has_courtyard: bool = False,
    description: str | None = None,
    url: str | None = None,
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
        city=(city or "").strip() or None,
        postal_code=(postal_code or "").strip() or None,
        street_address=(street_address or "").strip() or None,
        latitude=latitude,
        longitude=longitude,
        year_built=year_built,
        has_elevator=bool(has_elevator),
        has_parking=bool(has_parking),
        has_sauna=bool(has_sauna),
        has_courtyard=bool(has_courtyard),
        description=(description or "").strip() or None,
        url=(url or "").strip() or None,
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
    city: str | None = None,
    postal_code: str | None = None,
    street_address: str | None = None,
    latitude: Decimal | None = None,
    longitude: Decimal | None = None,
    year_built: int | None = None,
    has_elevator: bool = False,
    has_parking: bool = False,
    has_sauna: bool = False,
    has_courtyard: bool = False,
    description: str | None = None,
    url: str | None = None,
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
    row.city = (city or "").strip() or None
    row.postal_code = (postal_code or "").strip() or None
    row.street_address = (street_address or "").strip() or None
    row.latitude = latitude
    row.longitude = longitude
    row.year_built = year_built
    row.has_elevator = bool(has_elevator)
    row.has_parking = bool(has_parking)
    row.has_sauna = bool(has_sauna)
    row.has_courtyard = bool(has_courtyard)
    row.description = (description or "").strip() or None
    row.url = (url or "").strip() or None
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
    floor: int | None = None,
    area_sqm: Decimal | None = None,
    bedrooms: int | None = 0,
    has_kitchen: bool = False,
    has_bathroom: bool = True,
    has_balcony: bool = False,
    has_terrace: bool = False,
    has_dishwasher: bool = False,
    has_washing_machine: bool = False,
    has_tv: bool = False,
    has_wifi: bool = True,
    max_guests: int | None = 2,
    description: str | None = None,
    floor_plan_image_id: int | None = None,
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
    bedrooms_value = 0 if bedrooms is None else bedrooms
    max_guests_value = 2 if max_guests is None else max_guests
    if max_guests_value < 1:
        raise PropertyServiceError(
            code="validation_error",
            message="Field 'max_guests' must be at least 1.",
            status=400,
        )
    if bedrooms_value < 0:
        raise PropertyServiceError(
            code="validation_error",
            message="Field 'bedrooms' cannot be negative.",
            status=400,
        )

    row = Unit(
        property_id=property_id,
        name=normalized_name,
        unit_type=(unit_type or "").strip() or None,
        floor=floor,
        area_sqm=area_sqm,
        bedrooms=bedrooms_value,
        has_kitchen=bool(has_kitchen),
        has_bathroom=bool(has_bathroom),
        has_balcony=bool(has_balcony),
        has_terrace=bool(has_terrace),
        has_dishwasher=bool(has_dishwasher),
        has_washing_machine=bool(has_washing_machine),
        has_tv=bool(has_tv),
        has_wifi=bool(has_wifi),
        max_guests=max_guests_value,
        description=(description or "").strip() or None,
        floor_plan_image_id=floor_plan_image_id,
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
    floor: int | None = None,
    area_sqm: Decimal | None = None,
    bedrooms: int | None = 0,
    has_kitchen: bool = False,
    has_bathroom: bool = True,
    has_balcony: bool = False,
    has_terrace: bool = False,
    has_dishwasher: bool = False,
    has_washing_machine: bool = False,
    has_tv: bool = False,
    has_wifi: bool = True,
    max_guests: int | None = 2,
    description: str | None = None,
    floor_plan_image_id: int | None = None,
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
    bedrooms_value = row.bedrooms if bedrooms is None else bedrooms
    max_guests_value = row.max_guests if max_guests is None else max_guests
    if max_guests_value < 1:
        raise PropertyServiceError(
            code="validation_error",
            message="Field 'max_guests' must be at least 1.",
            status=400,
        )
    if bedrooms_value < 0:
        raise PropertyServiceError(
            code="validation_error",
            message="Field 'bedrooms' cannot be negative.",
            status=400,
        )

    row.name = normalized_name
    row.unit_type = (unit_type or "").strip() or None
    row.floor = floor
    row.area_sqm = area_sqm
    row.bedrooms = bedrooms_value
    row.has_kitchen = bool(has_kitchen)
    row.has_bathroom = bool(has_bathroom)
    row.has_balcony = bool(has_balcony)
    row.has_terrace = bool(has_terrace)
    row.has_dishwasher = bool(has_dishwasher)
    row.has_washing_machine = bool(has_washing_machine)
    row.has_tv = bool(has_tv)
    row.has_wifi = bool(has_wifi)
    row.max_guests = max_guests_value
    row.description = (description or "").strip() or None
    row.floor_plan_image_id = floor_plan_image_id
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
