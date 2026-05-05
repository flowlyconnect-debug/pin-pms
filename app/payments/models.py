from __future__ import annotations

from datetime import datetime

from app.extensions import db

PAYMENT_PROVIDERS = frozenset({"stripe", "paytrail"})
PAYMENT_STATUSES = frozenset(
    {"pending", "succeeded", "failed", "refunded", "partially_refunded", "expired"}
)
PAYMENT_METHODS = frozenset({"card", "bank", "mobilepay", "other"})
REFUND_STATUSES = frozenset({"pending", "succeeded", "failed"})


class Payment(db.Model):
    __tablename__ = "payments"
    __table_args__ = (
        db.UniqueConstraint(
            "provider",
            "provider_payment_id",
            name="uq_payments_provider_provider_payment_id",
        ),
        db.UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
        db.Index("ix_payments_organization_id", "organization_id"),
        db.Index("ix_payments_invoice_id", "invoice_id"),
        db.Index("ix_payments_reservation_id", "reservation_id"),
        db.Index("ix_payments_status", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=True)
    reservation_id = db.Column(db.Integer, db.ForeignKey("reservations.id"), nullable=True)

    provider = db.Column(db.String(32), nullable=False)
    provider_payment_id = db.Column(db.String(128), nullable=True)
    provider_session_id = db.Column(db.String(128), nullable=True)

    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="EUR")
    status = db.Column(db.String(32), nullable=False, default="pending")
    method = db.Column(db.String(32), nullable=True)

    last_error = db.Column(db.Text, nullable=True)
    idempotency_key = db.Column(db.String(128), nullable=True, unique=True)

    return_url = db.Column(db.String(512), nullable=True)
    cancel_url = db.Column(db.String(512), nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at = db.Column(db.DateTime, nullable=True)


class PaymentRefund(db.Model):
    __tablename__ = "payment_refunds"

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    provider_refund_id = db.Column(db.String(128), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="pending")
    idempotency_key = db.Column(db.String(128), nullable=True, unique=True)
    last_error = db.Column(db.Text, nullable=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

