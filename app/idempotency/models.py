from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


class IdempotencyKey(db.Model):
    """Stores idempotency metadata and optional cached API responses."""

    __tablename__ = "idempotency_keys"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(128), unique=True, nullable=False, index=True)
    endpoint = db.Column(db.String(128), nullable=False)
    request_hash = db.Column(db.String(64), nullable=False)
    response_status = db.Column(db.Integer, nullable=True)
    response_body = db.Column(db.Text, nullable=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
