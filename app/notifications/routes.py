from __future__ import annotations

from collections import OrderedDict

from app.notifications.models import Notification


def to_payload(row: Notification) -> dict:
    return {
        "id": row.id,
        "type": row.type,
        "title": row.title,
        "body": row.body,
        "link": row.link,
        "severity": row.severity,
        "is_read": bool(row.is_read),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "read_at": row.read_at.isoformat() if row.read_at else None,
    }


def group_by_day(rows: list[Notification]) -> list[dict]:
    grouped: OrderedDict[str, list[dict]] = OrderedDict()
    for row in rows:
        day_key = row.created_at.date().isoformat() if row.created_at else "unknown"
        grouped.setdefault(day_key, []).append(to_payload(row))
    return [{"day": day, "items": items} for day, items in grouped.items()]
