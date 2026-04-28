from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def normalize_device(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_device_id": str(payload.get("id") or payload.get("device_id") or "").strip(),
        "name": str(payload.get("name") or payload.get("label") or "Pindora Lock").strip(),
        "status": str(payload.get("status") or "unknown").strip().lower(),
        "battery_level": _to_int_or_none(payload.get("battery_level")),
        "last_seen_at": _parse_dt(payload.get("last_seen_at")),
    }


def normalize_code_create(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_code_id": str(payload.get("code_id") or payload.get("id") or "").strip() or None,
        "status": str(payload.get("status") or "created").strip().lower(),
    }


def _to_int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
