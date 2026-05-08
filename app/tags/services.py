from __future__ import annotations

from dataclasses import dataclass

from app.audit import record as audit_record
from app.extensions import db
from app.guests.models import Guest
from app.properties.models import Property, Unit
from app.reservations.models import Reservation
from app.tags.models import GuestTag, PropertyTag, ReservationTag, Tag

ALLOWED_TAG_COLORS = ("green", "yellow", "red", "blue", "purple", "orange", "gray", "black")
TARGET_TYPES = ("guest", "reservation", "property")


@dataclass
class TagServiceError(Exception):
    code: str
    message: str
    status: int


class TagService:
    @staticmethod
    def create(organization_id: int, name: str, color: str, created_by_user_id: int) -> Tag:
        cleaned_name = (name or "").strip()
        cleaned_color = (color or "").strip().lower()
        if not cleaned_name:
            raise TagServiceError("validation_error", "Tag name is required.", 400)
        if len(cleaned_name) > 64:
            raise TagServiceError("validation_error", "Tag name max length is 64.", 400)
        if cleaned_color not in ALLOWED_TAG_COLORS:
            raise TagServiceError("validation_error", "Invalid tag color.", 400)
        if Tag.query.filter_by(organization_id=organization_id).count() >= 100:
            raise TagServiceError(
                "validation_error", "Tag limit (100) reached for organization.", 400
            )
        existing = Tag.query.filter_by(organization_id=organization_id, name=cleaned_name).first()
        if existing is not None:
            raise TagServiceError("conflict", "Tag name already exists in organization.", 409)
        tag = Tag(
            organization_id=organization_id,
            name=cleaned_name,
            color=cleaned_color,
            created_by_user_id=created_by_user_id,
        )
        db.session.add(tag)
        db.session.flush()
        audit_record(
            "tag.created",
            organization_id=organization_id,
            target_type="tag",
            target_id=tag.id,
            metadata={"name": tag.name, "color": tag.color},
            commit=False,
        )
        return tag

    @staticmethod
    def _resolve_target(organization_id: int, target_type: str, target_id: int) -> None:
        if target_type == "guest":
            row = Guest.query.filter_by(id=target_id, organization_id=organization_id).first()
        elif target_type == "property":
            row = Property.query.filter_by(id=target_id, organization_id=organization_id).first()
        elif target_type == "reservation":
            row = (
                Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
                .join(Property, Unit.property_id == Property.id)
                .filter(Reservation.id == target_id, Property.organization_id == organization_id)
                .first()
            )
        else:
            raise TagServiceError("validation_error", "Invalid target_type.", 400)
        if row is None:
            raise TagServiceError("not_found", "Target resource not found in organization.", 404)

    @staticmethod
    def _association_model(target_type: str):
        if target_type == "guest":
            return GuestTag, "guest_id"
        if target_type == "reservation":
            return ReservationTag, "reservation_id"
        if target_type == "property":
            return PropertyTag, "property_id"
        raise TagServiceError("validation_error", "Invalid target_type.", 400)

    @staticmethod
    def attach(
        organization_id: int, target_type: str, target_id: int, tag_id: int, actor_user_id: int
    ) -> None:
        if target_type not in TARGET_TYPES:
            raise TagServiceError("validation_error", "Invalid target_type.", 400)
        tag = Tag.query.filter_by(id=tag_id, organization_id=organization_id).first()
        if tag is None:
            raise TagServiceError("not_found", "Tag not found.", 404)
        TagService._resolve_target(organization_id, target_type, target_id)
        model, target_key = TagService._association_model(target_type)
        existing = model.query.filter_by(**{target_key: target_id, "tag_id": tag_id}).first()
        if existing is None:
            db.session.add(model(**{target_key: target_id, "tag_id": tag_id}))
            db.session.flush()
        audit_record(
            "tag.attached",
            actor_id=actor_user_id,
            organization_id=organization_id,
            target_type=target_type,
            target_id=target_id,
            metadata={"tag_id": tag_id},
            commit=False,
        )

    @staticmethod
    def detach(
        organization_id: int, target_type: str, target_id: int, tag_id: int, actor_user_id: int
    ) -> None:
        if target_type not in TARGET_TYPES:
            raise TagServiceError("validation_error", "Invalid target_type.", 400)
        tag = Tag.query.filter_by(id=tag_id, organization_id=organization_id).first()
        if tag is None:
            raise TagServiceError("not_found", "Tag not found.", 404)
        TagService._resolve_target(organization_id, target_type, target_id)
        model, target_key = TagService._association_model(target_type)
        model.query.filter_by(**{target_key: target_id, "tag_id": tag_id}).delete(
            synchronize_session=False
        )
        db.session.flush()
        audit_record(
            "tag.detached",
            actor_id=actor_user_id,
            organization_id=organization_id,
            target_type=target_type,
            target_id=target_id,
            metadata={"tag_id": tag_id},
            commit=False,
        )

    @staticmethod
    def list_for_target(organization_id: int, target_type: str, target_id: int) -> list[Tag]:
        TagService._resolve_target(organization_id, target_type, target_id)
        if target_type == "guest":
            query = Tag.query.join(GuestTag, GuestTag.tag_id == Tag.id).filter(
                GuestTag.guest_id == target_id
            )
        elif target_type == "reservation":
            query = Tag.query.join(ReservationTag, ReservationTag.tag_id == Tag.id).filter(
                ReservationTag.reservation_id == target_id
            )
        elif target_type == "property":
            query = Tag.query.join(PropertyTag, PropertyTag.tag_id == Tag.id).filter(
                PropertyTag.property_id == target_id
            )
        else:
            raise TagServiceError("validation_error", "Invalid target_type.", 400)
        return (
            query.filter(Tag.organization_id == organization_id)
            .order_by(Tag.name.asc(), Tag.id.asc())
            .all()
        )

    @staticmethod
    def list_for_org(organization_id: int) -> list[Tag]:
        return (
            Tag.query.filter_by(organization_id=organization_id)
            .order_by(Tag.name.asc(), Tag.id.asc())
            .all()
        )
