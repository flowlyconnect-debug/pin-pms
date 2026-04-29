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
import os
import secrets

from flask import current_app, has_app_context
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


def _password_min_length() -> int:
    if has_app_context():
        raw = str(current_app.config.get("PASSWORD_MIN_LENGTH", "12")).strip()
    else:
        raw = (os.getenv("PASSWORD_MIN_LENGTH") or "12").strip()
    try:
        value = int(raw)
    except ValueError:
        return 12
    return value if value > 0 else 12


def validate_password_strength(password: str) -> list[str]:
    """Return policy violations for ``password``.

    Rules:
    - minimum length from ``PASSWORD_MIN_LENGTH`` (default 12)
    - at least one letter
    - at least one number
    """

    candidate = password or ""
    errors: list[str] = []
    min_length = _password_min_length()
    if len(candidate) < min_length:
        errors.append(f"Password must be at least {min_length} characters long.")
    if not any(char.isalpha() for char in candidate):
        errors.append("Password must include at least one letter.")
    if not any(char.isdigit() for char in candidate):
        errors.append("Password must include at least one number.")
    return errors
