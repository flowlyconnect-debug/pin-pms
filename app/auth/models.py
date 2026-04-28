"""Auth models — currently the password-reset token only.

Project brief section 4: "salasanan resetointi sähköpostilla". Tokens
are single-use, time-bounded, and stored only as SHA-256 digests so a
DB leak does not expose pending reset links.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.security import generate_token, hash_token
from app.extensions import db


# How long a freshly-issued reset link stays valid. The brief does not
# fix a number; 1h is the conventional default and is short enough to
# limit the impact of a leaked email forward.
PASSWORD_RESET_TTL = timedelta(hours=1)
EMAIL_2FA_TTL = timedelta(minutes=10)


class PasswordResetToken(db.Model):
    __tablename__ = "password_reset_tokens"

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
    def issue(cls, *, user_id: int, ttl: timedelta = PASSWORD_RESET_TTL) -> tuple["PasswordResetToken", str]:
        """Create and persist a new token. Returns ``(row, raw_token)``.

        The raw token is only emitted here — the DB stores the hash.
        """

        raw = generate_token(32)
        row = cls(
            user_id=user_id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(timezone.utc) + ttl,
        )
        return row, raw

    @classmethod
    def find_active_by_raw(cls, raw_token: str) -> "PasswordResetToken | None":
        """Look up a token that is still valid (unused + unexpired)."""

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


class TwoFactorEmailCode(db.Model):
    __tablename__ = "two_factor_email_codes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash = db.Column(db.String(128), nullable=False, unique=True, index=True)
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
        cls, *, user_id: int, code: str, ttl: timedelta = EMAIL_2FA_TTL
    ) -> "TwoFactorEmailCode":
        return cls(
            user_id=user_id,
            code_hash=hash_token(code),
            expires_at=datetime.now(timezone.utc) + ttl,
        )

    @classmethod
    def consume_active_code(cls, *, user_id: int, raw_code: str) -> bool:
        if not raw_code:
            return False
        now = datetime.now(timezone.utc)
        row = (
            cls.query.filter_by(
                user_id=user_id,
                code_hash=hash_token(raw_code),
                used_at=None,
            )
            .filter(cls.expires_at >= now)
            .order_by(cls.id.desc())
            .first()
        )
        if row is None:
            return False
        row.used_at = now
        return True


class LoginAttempt(db.Model):
    __tablename__ = "login_attempts"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    ip = db.Column(db.String(64), nullable=True)
    success = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
