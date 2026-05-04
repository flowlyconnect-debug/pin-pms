"""Fernet wrapper for outbound webhook signing secrets (at-rest encryption)."""

from __future__ import annotations

import base64

from flask import current_app

from app.core.security import hash_token


def webhook_fernet():
    """Return a Fernet instance using ``CHECKIN_FERNET_KEY`` or a deterministic dev fallback."""

    try:
        from cryptography.fernet import Fernet
    except Exception:  # noqa: BLE001
        return None

    key = (current_app.config.get("CHECKIN_FERNET_KEY") or "").strip()
    if key:
        return Fernet(key.encode("utf-8"))
    fallback = base64.urlsafe_b64encode(
        hash_token(current_app.config.get("SECRET_KEY", "")).encode("utf-8")[:32]
    )
    return Fernet(fallback)


def encrypt_signing_secret(plaintext: str) -> str:
    f = webhook_fernet()
    if f is None:
        raise RuntimeError("cryptography.fernet is required for webhook signing secrets.")
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_signing_secret(token: str) -> str:
    f = webhook_fernet()
    if f is None:
        raise RuntimeError("cryptography.fernet is required for webhook signing secrets.")
    return f.decrypt(token.encode("utf-8")).decode("utf-8")
