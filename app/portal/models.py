from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.core.security import generate_token, hash_token
from app.extensions import db

PORTAL_MAGIC_LINK_TTL = timedelta(minutes=20)


class PortalMagicLinkToken(db.Model):
    __tablename__ = "portal_magic_link_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash = db.Column(db.String(128), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    user = db.relationship("User", lazy="joined")

    @classmethod
    def issue(
        cls,
        *,
        user_id: int,
        ttl: timedelta = PORTAL_MAGIC_LINK_TTL,
    ) -> tuple["PortalMagicLinkToken", str]:
        raw = generate_token(32)
        row = cls(
            user_id=user_id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(timezone.utc) + ttl,
        )
        return row, raw

    @classmethod
    def find_active_by_raw(cls, raw_token: str) -> "PortalMagicLinkToken | None":
        if not raw_token:
            return None
        row = cls.query.filter_by(token_hash=hash_token(raw_token)).first()
        if row is None:
            return None
        if row.used_at is not None:
            return None
        if row.expires_at < datetime.now(timezone.utc):
            return None
        return row

    def mark_used(self) -> None:
        self.used_at = datetime.now(timezone.utc)


class LockDevice(db.Model):
    __tablename__ = "lock_devices"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    unit_id = db.Column(
        db.Integer,
        db.ForeignKey("units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = db.Column(db.String(32), nullable=False, default="pindora")
    provider_device_id = db.Column(db.String(128), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="unknown")
    battery_level = db.Column(db.Integer, nullable=True)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AccessCode(db.Model):
    __tablename__ = "access_codes"

    id = db.Column(db.Integer, primary_key=True)
    reservation_id = db.Column(
        db.Integer,
        db.ForeignKey("reservations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lock_device_id = db.Column(
        db.Integer,
        db.ForeignKey("lock_devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash = db.Column(db.String(128), nullable=False)
    provider_code_id = db.Column(db.String(128), nullable=True)
    idempotency_key = db.Column(db.String(128), nullable=True, unique=True, index=True)
    valid_from = db.Column(db.DateTime(timezone=True), nullable=False)
    valid_until = db.Column(db.DateTime(timezone=True), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    revoked_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class PortalCheckInToken(db.Model):
    __tablename__ = "portal_checkin_tokens"

    id = db.Column(db.Integer, primary_key=True)
    reservation_id = db.Column(
        db.Integer,
        db.ForeignKey("reservations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash = db.Column(db.String(128), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    @classmethod
    def issue(
        cls,
        *,
        reservation_id: int,
        ttl: timedelta = timedelta(days=7),
    ) -> tuple["PortalCheckInToken", str]:
        raw = generate_token(32)
        row = cls(
            reservation_id=reservation_id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(timezone.utc) + ttl,
        )
        return row, raw

    @classmethod
    def find_active_by_raw(cls, raw_token: str) -> "PortalCheckInToken | None":
        if not raw_token:
            return None
        row = cls.query.filter_by(token_hash=hash_token(raw_token)).first()
        if row is None:
            return None
        if row.used_at is not None:
            return None
        if row.expires_at < datetime.now(timezone.utc):
            return None
        return row

    def mark_used(self) -> None:
        self.used_at = datetime.now(timezone.utc)


class GuestCheckIn(db.Model):
    __tablename__ = "guest_checkins"

    id = db.Column(db.Integer, primary_key=True)
    reservation_id = db.Column(
        db.Integer,
        db.ForeignKey("reservations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    full_name = db.Column(db.String(255), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    id_document_path = db.Column(db.Text, nullable=False)
    rules_accepted = db.Column(db.Boolean, nullable=False, default=False)
    rules_signature = db.Column(db.String(255), nullable=False)
    checked_in_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    checked_out_at = db.Column(db.DateTime(timezone=True), nullable=True)

