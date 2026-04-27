"""Small generic helpers shared across modules — project brief section 2."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse


def utcnow() -> datetime:
    """Return a timezone-aware UTC ``datetime`` (avoids deprecated ``utcnow``)."""

    return datetime.now(timezone.utc)


def safe_relative_url(target: str | None) -> str | None:
    """Return ``target`` only if it is a same-origin relative path.

    Used by the auth flow to prevent open-redirect attacks via a
    malicious ``?next=`` query parameter.
    """

    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    if not target.startswith("/"):
        return None
    return target


def human_filesize(num_bytes: int | None) -> str:
    """Format ``num_bytes`` as a short human string (KB / MB / GB)."""

    if num_bytes is None:
        return "—"
    n = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
