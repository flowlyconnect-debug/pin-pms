from __future__ import annotations

from datetime import date, datetime, timezone

from app.extensions import db
from app.models import TimestampMixin


class PropertyOwner(TimestampMixin, db.Model):
    __tablename__ = "property_owners"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    phone = db.Column(db.String(64), nullable=True)
    payout_iban = db.Column(db.String(64), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class PropertyOwnerAssignment(TimestampMixin, db.Model):
    __tablename__ = "property_owner_assignments"

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(
        db.Integer,
        db.ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id = db.Column(
        db.Integer,
        db.ForeignKey("property_owners.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ownership_pct = db.Column(db.Numeric(5, 4), nullable=False, default=1)
    management_fee_pct = db.Column(db.Numeric(5, 4), nullable=False, default=0)
    valid_from = db.Column(db.Date, nullable=False, default=date.today)
    valid_to = db.Column(db.Date, nullable=True)


class OwnerPayoutStatus:
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    ALL = (DRAFT, SENT, PAID)


class OwnerPayout(TimestampMixin, db.Model):
    __tablename__ = "owner_payouts"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(
        db.Integer,
        db.ForeignKey("property_owners.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_month = db.Column(db.String(7), nullable=False, index=True)  # YYYY-MM
    gross_revenue_cents = db.Column(db.Integer, nullable=False, default=0)
    management_fee_cents = db.Column(db.Integer, nullable=False, default=0)
    expenses_cents = db.Column(db.Integer, nullable=False, default=0)
    net_payout_cents = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(16), nullable=False, default=OwnerPayoutStatus.DRAFT, index=True)
    pdf_path = db.Column(db.String(512), nullable=True)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    paid_at = db.Column(db.DateTime(timezone=True), nullable=True)


class OwnerUser(db.Model):
    __tablename__ = "owner_users"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(
        db.Integer,
        db.ForeignKey("property_owners.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
