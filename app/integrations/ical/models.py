from __future__ import annotations

from app.extensions import db
from app.models import TimestampMixin


class ImportedCalendarFeed(TimestampMixin, db.Model):
    __tablename__ = "imported_calendar_feeds"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    unit_id = db.Column(
        db.Integer,
        db.ForeignKey("units.id"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(255), nullable=True)
    source_url = db.Column(db.String(2048), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_error = db.Column(db.String(512), nullable=True)

    unit = db.relationship("Unit", lazy="joined")


class ImportedCalendarEvent(TimestampMixin, db.Model):
    __tablename__ = "imported_calendar_events"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    unit_id = db.Column(
        db.Integer,
        db.ForeignKey("units.id"),
        nullable=False,
        index=True,
    )
    feed_id = db.Column(
        db.Integer,
        db.ForeignKey("imported_calendar_feeds.id"),
        nullable=False,
        index=True,
    )
    external_uid = db.Column(db.String(255), nullable=False)
    summary = db.Column(db.String(512), nullable=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    unit = db.relationship("Unit", lazy="joined")
    feed = db.relationship("ImportedCalendarFeed", lazy="joined")
