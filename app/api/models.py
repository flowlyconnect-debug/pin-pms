"""API key model.

API keys are issued per user/organization and used to authenticate public API
requests. The plaintext key value is only shown once at creation time — the
database only stores a SHA-256 hash plus a short prefix for identification in
logs and admin UIs. SHA-256 is sufficient here because the raw key is
high-entropy (``secrets.token_urlsafe(32)`` → ~256 bits), so slow hashes like
bcrypt are unnecessary and would only make request-path auth slower.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from app.extensions import db


API_KEY_RAW_PREFIX = "pms_"
API_KEY_PREFIX_LENGTH = 12  # Length of the stored ``key_prefix`` (e.g. ``pms_abcd1234``).


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class ApiKey(db.Model):
    __tablename__ = "api_keys"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    name = db.Column(db.String(255), nullable=False)
    key_prefix = db.Column(db.String(32), nullable=False, index=True)
    key_hash = db.Column(db.String(128), nullable=False, unique=True, index=True)
    scopes = db.Column(db.String(512), nullable=False, default="")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    organization = db.relationship("Organization", lazy="joined")
    user = db.relationship("User", lazy="joined")

    # ------------------------------------------------------------------
    # Factory / lookup helpers
    # ------------------------------------------------------------------
    @classmethod
    def generate_raw_key(cls) -> str:
        """Return a new, high-entropy raw API key string.

        Format: ``pms_<urlsafe token>``. The ``pms_`` prefix makes secret-scanning
        tools easier to configure and helps humans spot the value in logs.
        """

        return f"{API_KEY_RAW_PREFIX}{secrets.token_urlsafe(32)}"

    @classmethod
    def issue(
        cls,
        *,
        name: str,
        organization_id: int,
        user_id: Optional[int] = None,
        scopes: str = "",
        expires_at: Optional[datetime] = None,
    ) -> tuple["ApiKey", str]:
        """Create a new ApiKey. Returns ``(api_key, raw_key)``.

        Only the returned ``raw_key`` exposes the plaintext — it must be shown to
        the operator immediately and never persisted anywhere other than the
        consumer's own secret store.
        """

        raw_key = cls.generate_raw_key()
        api_key = cls(
            name=name.strip(),
            organization_id=organization_id,
            user_id=user_id,
            scopes=scopes.strip(),
            expires_at=expires_at,
            key_prefix=raw_key[:API_KEY_PREFIX_LENGTH],
            key_hash=_hash_key(raw_key),
        )
        return api_key, raw_key

    @classmethod
    def find_active_by_raw_key(cls, raw_key: str) -> Optional["ApiKey"]:
        """Look up an active, non-expired key matching the supplied raw value."""

        if not raw_key:
            return None
        key = cls.query.filter_by(key_hash=_hash_key(raw_key)).first()
        if key is None:
            return None
        if not key.is_active:
            return None
        if key.expires_at is not None and key.expires_at < datetime.now(timezone.utc):
            return None
        return key

    # ------------------------------------------------------------------
    # Instance helpers
    # ------------------------------------------------------------------
    def touch(self) -> None:
        """Update the last-used timestamp. Caller is responsible for committing."""

        self.last_used_at = datetime.now(timezone.utc)

    @property
    def scope_list(self) -> list[str]:
        return [s.strip() for s in (self.scopes or "").split(",") if s.strip()]
