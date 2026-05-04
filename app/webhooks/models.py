"""ORM models for inbound webhook events and outbound webhook deliveries."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint

from app.extensions import db


class WebhookEvent(db.Model):
    """Inbound webhook payload record (Stripe, Visma Pay, Pindora Lock, …)."""

    __tablename__ = "webhook_events"

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(64), nullable=False)
    event_type = db.Column(db.String(128), nullable=False)
    external_id = db.Column(db.String(128), nullable=True)
    payload = db.Column(db.JSON, nullable=False)
    signature = db.Column(db.String(256), nullable=False, default="")
    signature_verified = db.Column(db.Boolean, nullable=False, default=False)
    processed = db.Column(db.Boolean, nullable=False, default=False)
    processing_error = db.Column(db.Text, nullable=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    processed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_id",
            name="uq_webhook_events_provider_external_id",
        ),
        db.Index(
            "ix_webhook_events_provider_processed",
            "provider",
            "processed",
        ),
    )


class WebhookSubscription(db.Model):
    """Tenant-scoped outbound webhook subscription."""

    __tablename__ = "webhook_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url = db.Column(db.String(512), nullable=False)
    secret_hash = db.Column(db.String(64), nullable=False)
    secret_encrypted = db.Column(db.Text, nullable=False)
    events = db.Column(db.JSON, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_delivery_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_delivery_status = db.Column(db.Integer, nullable=True)
    failure_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class WebhookDelivery(db.Model):
    """Outbound delivery attempt log."""

    __tablename__ = "webhook_deliveries"

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(
        db.Integer,
        db.ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = db.Column(db.String(128), nullable=False)
    payload = db.Column(db.JSON, nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    signature = db.Column(db.String(256), nullable=False)
    response_status = db.Column(db.Integer, nullable=True)
    response_body = db.Column(db.Text, nullable=True)
    attempt_number = db.Column(db.Integer, nullable=False, default=1)
    delivered_at = db.Column(db.DateTime(timezone=True), nullable=True)
    next_retry_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
