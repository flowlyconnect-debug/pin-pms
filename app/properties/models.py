from app.extensions import db
from app.models import TimestampMixin


class Property(TimestampMixin, db.Model):
    __tablename__ = "properties"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(255), nullable=False)
    address = db.Column(db.String(512), nullable=True)

    organization = db.relationship("Organization", back_populates="properties", lazy="joined")
    units = db.relationship("Unit", back_populates="property", lazy="select", cascade="all, delete-orphan")


class Unit(TimestampMixin, db.Model):
    __tablename__ = "units"

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(
        db.Integer,
        db.ForeignKey("properties.id"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(255), nullable=False)
    unit_type = db.Column(db.String(100), nullable=True)

    property = db.relationship("Property", back_populates="units", lazy="joined")
    reservations = db.relationship(
        "Reservation",
        back_populates="unit",
        lazy="select",
        cascade="all, delete-orphan",
    )
