from __future__ import annotations

from app.extensions import db
from app.models import TimestampMixin


class Expense(TimestampMixin, db.Model):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    property_id = db.Column(
        db.Integer,
        db.ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    category = db.Column(db.String(50), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    vat = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    date = db.Column(db.Date, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    payee = db.Column(db.String(255), nullable=True)
    attached_invoice_id = db.Column(
        db.Integer,
        db.ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    organization = db.relationship("Organization", lazy="joined")
    property = db.relationship("Property", lazy="joined")
    attached_invoice = db.relationship("Invoice", lazy="joined")
