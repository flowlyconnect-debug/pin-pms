from app.extensions import db
from app.models import TimestampMixin


class Guest(TimestampMixin, db.Model):
    __tablename__ = "guests"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    first_name = db.Column(db.String(120), nullable=False)
    last_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=True, index=True)
    phone = db.Column(db.String(80), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    preferences = db.Column(db.Text, nullable=True)

    organization = db.relationship("Organization", back_populates="guests", lazy="joined")
    reservations = db.relationship("Reservation", back_populates="guest", lazy="select")

    @property
    def full_name(self) -> str:
        return f"{(self.first_name or '').strip()} {(self.last_name or '').strip()}".strip()
