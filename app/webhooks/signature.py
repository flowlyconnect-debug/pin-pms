"""Shared HMAC-SHA256 helpers for webhook providers."""

from __future__ import annotations

import hashlib
import hmac


def hmac_sha256_hex_digest(*, secret: str, payload_bytes: bytes) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


def verify_hmac_sha256_hex(*, secret: str, payload_bytes: bytes, signature_header: str) -> bool:
    if not secret or not signature_header:
        return False
    expected = hmac_sha256_hex_digest(secret=secret, payload_bytes=payload_bytes)
    candidate = (signature_header or "").strip()
    if "," in candidate and "v1=" in candidate:
        for part in candidate.split(","):
            part = part.strip()
            if part.startswith("v1="):
                candidate = part[3:].strip()
                break
    if len(candidate) != len(expected):
        return False
    return hmac.compare_digest(expected, candidate)
