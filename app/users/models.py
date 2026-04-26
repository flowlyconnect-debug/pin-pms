from enum import Enum

from flask_login import UserMixin
import pyotp
import sqlalchemy as sa
from sqlalchemy import event
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import TimestampMixin


class UserRole(str, Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    USER = "user"
    API_CLIENT = "api_client"


class Organization(TimestampMixin, db.Model):
    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)

    users = db.relationship("User", back_populates="organization", lazy="select")
    properties = db.relationship("Property", back_populates="organization", lazy="select")
    guests = db.relationship("Guest", back_populates="organization", lazy="select")


class User(TimestampMixin, UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id"),
        nullable=False,
    )
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.Enum(
            UserRole,
            name="user_role_enum",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=UserRole.USER.value,
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    totp_secret = db.Column(db.String(32), nullable=True)
    is_2fa_enabled = db.Column(db.Boolean, nullable=False, default=False)
    organization = db.relationship("Organization", back_populates="users", lazy="joined")

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_superadmin(self) -> bool:
        return self.role == UserRole.SUPERADMIN.value

    def ensure_totp_secret(self) -> str:
        if not self.totp_secret:
            self.totp_secret = pyotp.random_base32()
        return self.totp_secret

    def verify_totp(self, code: str) -> bool:
        if not self.totp_secret:
            return False
        normalized_code = (code or "").strip()
        return pyotp.TOTP(self.totp_secret).verify(normalized_code, valid_window=1)


@event.listens_for(User, "after_insert")
def _ensure_shadow_guest_profile(_mapper, connection, target) -> None:
    """Backwards-compat: reservations used to reference users as guests."""

    from app.guests.models import Guest

    existing = connection.execute(
        sa.select(Guest.id).where(Guest.id == target.id)
    ).scalar_one_or_none()
    if existing is not None:
        return
    local_part = (target.email or "guest").split("@", 1)[0].strip() or "Guest"
    connection.execute(
        Guest.__table__.insert().values(
            id=target.id,
            organization_id=target.organization_id,
            first_name=local_part,
            last_name="",
            email=target.email,
            phone=None,
            notes=None,
            preferences=None,
        )
    )
