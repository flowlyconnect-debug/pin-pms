from app.extensions import db
from app.models import TimestampMixin


class Reservation(TimestampMixin, db.Model):
    __tablename__ = "reservations"
    __table_args__ = (
        db.Index("ix_reservations_unit_start_end", "unit_id", "start_date", "end_date"),
        db.Index("ix_reservations_status_end_date", "status", "end_date"),
        db.Index("ix_reservations_status_start_date", "status", "start_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(
        db.Integer,
        db.ForeignKey("units.id"),
        nullable=False,
        index=True,
    )
    guest_id = db.Column(db.Integer, db.ForeignKey("guests.id"), nullable=True, index=True)
    guest_name = db.Column(db.String(255), nullable=False, default="Guest")
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(50), nullable=False, default="confirmed")
    amount = db.Column(db.Numeric(10, 2), nullable=True)
    currency = db.Column(db.String(3), nullable=False, default="EUR")
    payment_status = db.Column(db.String(20), nullable=False, default="pending")
    invoice_number = db.Column(db.String(64), nullable=True, unique=True)
    invoice_date = db.Column(db.Date, nullable=True)
    due_date = db.Column(db.Date, nullable=True)

    unit = db.relationship("Unit", back_populates="reservations", lazy="joined")
    guest = db.relationship("Guest", back_populates="reservations", lazy="joined")
