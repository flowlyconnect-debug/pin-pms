"""Shared security helpers — project brief section 2 + section 10.

Centralises low-level password hashing, secret comparison, and token
generation so call sites do not import ``werkzeug`` / ``hashlib`` /
``secrets`` directly. Keeping these in one place makes it easier to swap
out the underlying primitives (e.g. switching from Werkzeug's PBKDF2 to
Argon2) without touching the call sites.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(raw_password: str) -> str:
    """Return a salted hash of ``raw_password`` suitable for DB storage."""

    return generate_password_hash(raw_password)


def verify_password(stored_hash: str, raw_password: str) -> bool:
    """Constant-time compare of a stored hash against the raw password."""

    if not stored_hash:
        return False
    return check_password_hash(stored_hash, raw_password)


def generate_token(num_bytes: int = 32) -> str:
    """Return a high-entropy URL-safe token (e.g. password reset, API key)."""

    return secrets.token_urlsafe(num_bytes)


def hash_token(raw_token: str) -> str:
    """Return a stable SHA-256 hex digest of a high-entropy token.

    Used for password-reset tokens and API keys: the raw value is
    long-random so a single SHA-256 round is sufficient — slow hashes only
    matter for low-entropy human passwords.
    """

    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    """Wrapper around ``hmac.compare_digest`` with friendly inputs."""

    return hmac.compare_digest((a or "").encode("utf-8"), (b or "").encode("utf-8"))
