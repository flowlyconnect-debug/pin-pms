from __future__ import annotations

from datetime import datetime

from app.extensions import db


class Tag(db.Model):
    __tablename__ = "tags"
    __table_args__ = (db.UniqueConstraint("organization_id", "name", name="uq_tags_org_name"),)

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)
    color = db.Column(db.String(16), nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class GuestTag(db.Model):
    __tablename__ = "guest_tags"

    guest_id = db.Column(db.Integer, db.ForeignKey("guests.id"), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey("tags.id"), primary_key=True)


class ReservationTag(db.Model):
    __tablename__ = "reservation_tags"

    reservation_id = db.Column(db.Integer, db.ForeignKey("reservations.id"), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey("tags.id"), primary_key=True)


class PropertyTag(db.Model):
    __tablename__ = "property_tags"

    property_id = db.Column(db.Integer, db.ForeignKey("properties.id"), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey("tags.id"), primary_key=True)
