"""Lease and Invoice models for tenant-scoped PMS billing."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import event
from sqlalchemy.ext.hybrid import hybrid_property

from app.extensions import db
from app.models import TimestampMixin


def _invoice_coerce_legacy_amount_only(target: "Invoice") -> None:
    """If only legacy ``amount`` was provided, treat it as a zero-VAT gross total."""

    amt = target.amount
    if amt is None:
        return
    total = target.total_incl_vat
    if total is None or Decimal(str(total)) == Decimal("0.00"):
        a = Decimal(str(amt)).quantize(Decimal("0.01"))
        target.amount = a
        target.total_incl_vat = a
        target.subtotal_excl_vat = a
        target.vat_amount = Decimal("0.00")
        target.vat_rate = Decimal("0.00")


class Lease(TimestampMixin, db.Model):
    __tablename__ = "leases"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    unit_id = db.Column(
        db.Integer,
        db.ForeignKey("units.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    guest_id = db.Column(
        db.Integer,
        db.ForeignKey("guests.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reservation_id = db.Column(
        db.Integer,
        db.ForeignKey("reservations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    rent_amount = db.Column(db.Numeric(12, 2), nullable=False)
    deposit_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    billing_cycle = db.Column(db.String(20), nullable=False, default="monthly")
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    updated_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = db.relationship("Organization", lazy="joined")
    unit = db.relationship("Unit", lazy="joined")
    guest = db.relationship("Guest", lazy="joined")
    reservation = db.relationship("Reservation", lazy="joined")
    created_by = db.relationship("User", foreign_keys=[created_by_id], lazy="joined")
    updated_by = db.relationship("User", foreign_keys=[updated_by_id], lazy="joined")
    invoices = db.relationship("Invoice", back_populates="lease", lazy="select")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Lease {self.id} org={self.organization_id}>"


class Invoice(TimestampMixin, db.Model):
    __tablename__ = "invoices"

    __table_args__ = (
        db.UniqueConstraint(
            "organization_id",
            "invoice_number",
            name="uq_invoices_organization_invoice_number",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lease_id = db.Column(
        db.Integer,
        db.ForeignKey("leases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reservation_id = db.Column(
        db.Integer,
        db.ForeignKey("reservations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    guest_id = db.Column(
        db.Integer,
        db.ForeignKey("guests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    invoice_number = db.Column(db.String(64), nullable=True, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    vat_rate = db.Column(db.Numeric(5, 2), nullable=False, default=24.00)
    vat_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    subtotal_excl_vat = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    total_incl_vat = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    currency = db.Column(db.String(3), nullable=False, default="EUR")
    due_date = db.Column(db.Date, nullable=False, index=True)
    paid_at = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    description = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)
    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    updated_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = db.relationship("Organization", lazy="joined")
    lease = db.relationship("Lease", back_populates="invoices", lazy="joined")
    reservation = db.relationship("Reservation", lazy="joined")
    guest = db.relationship("Guest", lazy="joined")
    created_by = db.relationship("User", foreign_keys=[created_by_id], lazy="joined")
    updated_by = db.relationship("User", foreign_keys=[updated_by_id], lazy="joined")

    @hybrid_property
    def total(self):
        """Backward-compatible gross total (ALV sisällä)."""

        return self.total_incl_vat

    @total.expression  # type: ignore[no-redef]
    def total(cls):
        return cls.total_incl_vat

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Invoice {self.id} org={self.organization_id}>"


@event.listens_for(Invoice, "before_insert")
def _invoice_before_insert(_mapper, _connection, target: Invoice) -> None:
    _invoice_coerce_legacy_amount_only(target)
