from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from icalendar import Calendar


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        parsed = value.dt
    except Exception:  # noqa: BLE001
        return None
    if isinstance(parsed, datetime):
        return parsed.date()
    if isinstance(parsed, date):
        return parsed
    return None


def parse_ical_events(payload: bytes) -> list[dict]:
    cal = Calendar.from_ical(payload)
    out: list[dict] = []
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        start_date = _to_date(component.get("dtstart"))
        end_date = _to_date(component.get("dtend"))
        if start_date is None:
            continue
        if end_date is None:
            end_date = start_date + timedelta(days=1)
        if end_date <= start_date:
            end_date = start_date + timedelta(days=1)
        out.append(
            {
                "uid": str(component.get("uid") or f"no-uid-{start_date.isoformat()}"),
                "summary": str(component.get("summary") or "").strip() or None,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
    return out
