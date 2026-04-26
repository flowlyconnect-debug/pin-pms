from app.extensions import db
from app.models import TimestampMixin


class Reservation(TimestampMixin, db.Model):
    __tablename__ = "reservations"

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(
        db.Integer,
        db.ForeignKey("units.id"),
        nullable=False,
        index=True,
    )
    guest_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(50), nullable=False, default="confirmed")

    unit = db.relationship("Unit", back_populates="reservations", lazy="joined")
    guest = db.relationship("User", back_populates="reservations", lazy="joined")
