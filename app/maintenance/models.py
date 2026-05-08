"""Maintenance request (work order) ORM model."""

from __future__ import annotations

import builtins

from app.extensions import db
from app.models import TimestampMixin


class MaintenanceRequest(TimestampMixin, db.Model):
    """Single-table work order: one row per maintenance request."""

    __tablename__ = "maintenance_requests"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    property_id = db.Column(
        db.Integer,
        db.ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    unit_id = db.Column(
        db.Integer,
        db.ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    guest_id = db.Column(
        db.Integer,
        db.ForeignKey("guests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reservation_id = db.Column(
        db.Integer,
        db.ForeignKey("reservations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="new", index=True)
    priority = db.Column(db.String(20), nullable=False, default="normal", index=True)
    assigned_to_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    due_date = db.Column(db.Date, nullable=True, index=True)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    property = db.relationship("Property", lazy="joined")
    unit = db.relationship("Unit", lazy="joined")
    guest = db.relationship("Guest", lazy="joined")
    reservation = db.relationship("Reservation", lazy="joined")
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id], lazy="joined")
    created_by = db.relationship("User", foreign_keys=[created_by_id], lazy="joined")
    PRIORITY_LABELS = {
        "low": "Matala",
        "normal": "Normaali",
        "medium": "Keskitaso",
        "high": "Korkea",
        "urgent": "Kiireellinen",
    }

    @builtins.property
    def priority_label(self) -> str:
        return self.PRIORITY_LABELS.get((self.priority or "").strip().lower(), "-")

    @classmethod
    def priority_label_for(cls, value: str | None) -> str:
        key = (value or "").strip().lower()
        return cls.PRIORITY_LABELS.get(key, "-")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MaintenanceRequest {self.id} org={self.organization_id} status={self.status!r}>"
