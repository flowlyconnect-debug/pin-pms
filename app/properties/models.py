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
    city = db.Column(db.String(100), nullable=True, index=True)
    postal_code = db.Column(db.String(10), nullable=True)
    street_address = db.Column(db.String(200), nullable=True)
    latitude = db.Column(db.Numeric(10, 7), nullable=True)
    longitude = db.Column(db.Numeric(10, 7), nullable=True)
    year_built = db.Column(db.Integer, nullable=True)
    has_elevator = db.Column(db.Boolean, nullable=False, default=False)
    has_parking = db.Column(db.Boolean, nullable=False, default=False)
    has_sauna = db.Column(db.Boolean, nullable=False, default=False)
    has_courtyard = db.Column(db.Boolean, nullable=False, default=False)
    has_air_conditioning = db.Column(db.Boolean, nullable=False, default=False)
    description = db.Column(db.Text, nullable=True)
    url = db.Column(db.String(500), nullable=True)

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
    floor = db.Column(db.Integer, nullable=True)
    area_sqm = db.Column(db.Numeric(6, 2), nullable=True)
    bedrooms = db.Column(db.Integer, nullable=False, default=0)
    has_kitchen = db.Column(db.Boolean, nullable=False, default=False)
    has_bathroom = db.Column(db.Boolean, nullable=False, default=True)
    has_balcony = db.Column(db.Boolean, nullable=False, default=False)
    has_terrace = db.Column(db.Boolean, nullable=False, default=False)
    has_dishwasher = db.Column(db.Boolean, nullable=False, default=False)
    has_washing_machine = db.Column(db.Boolean, nullable=False, default=False)
    has_tv = db.Column(db.Boolean, nullable=False, default=False)
    has_wifi = db.Column(db.Boolean, nullable=False, default=True)
    max_guests = db.Column(db.Integer, nullable=False, default=2)
    description = db.Column(db.Text, nullable=True)
    floor_plan_image_id = db.Column(
        db.Integer,
        db.ForeignKey("property_images.id", ondelete="SET NULL"),
        nullable=True,
    )

    property = db.relationship("Property", back_populates="units", lazy="joined")
    floor_plan_image = db.relationship(
        "PropertyImage", foreign_keys=[floor_plan_image_id], lazy="joined"
    )
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
    uploaded_by = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    property = db.relationship("Property", back_populates="images", lazy="joined")
