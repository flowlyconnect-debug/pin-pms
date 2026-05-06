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
    units = db.relationship(
        "Unit", back_populates="property", lazy="select", cascade="all, delete-orphan"
    )
    images = db.relationship(
        "PropertyImage",
        back_populates="property",
        lazy="select",
        cascade="all, delete-orphan",
        order_by="PropertyImage.sort_order.asc()",
    )


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


class PropertyImage(TimestampMixin, db.Model):
    __tablename__ = "property_images"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    property_id = db.Column(
        db.Integer,
        db.ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url = db.Column(db.String(1024), nullable=False)
    thumbnail_url = db.Column(db.String(1024), nullable=False)
    storage_key = db.Column(db.String(1024), nullable=False)
    thumbnail_storage_key = db.Column(db.String(1024), nullable=False)
    alt_text = db.Column(db.String(255), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    file_size = db.Column(db.Integer, nullable=False)
    content_type = db.Column(db.String(100), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    property = db.relationship("Property", back_populates="images", lazy="joined")
