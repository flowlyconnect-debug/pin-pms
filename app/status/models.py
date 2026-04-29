from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


class StatusComponent(db.Model):
    __tablename__ = "status_components"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), nullable=False, unique=True, index=True)
    name = db.Column(db.String(128), nullable=False)
    current_state = db.Column(db.String(32), nullable=False, default="operational", index=True)
    scheduled_maintenance = db.Column(db.Boolean, nullable=False, default=False)


class StatusIncident(db.Model):
    __tablename__ = "status_incidents"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    started_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    component_keys = db.Column(db.JSON, nullable=False, default=list)
    severity = db.Column(db.String(32), nullable=False, default="minor")
    status = db.Column(db.String(32), nullable=False, default="open", index=True)


class StatusCheck(db.Model):
    __tablename__ = "status_checks"

    id = db.Column(db.Integer, primary_key=True)
    component_key = db.Column(db.String(64), nullable=False, index=True)
    checked_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    ok = db.Column(db.Boolean, nullable=False, default=True)
    latency_ms = db.Column(db.Integer, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
