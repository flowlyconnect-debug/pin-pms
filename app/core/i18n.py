"""UI label helpers for Finnish-facing enum text."""

from __future__ import annotations

STATUS_LABELS_FI = {
    "draft": "Luonnos",
    "active": "Aktiivinen",
    "ended": "Päättynyt",
    "cancelled": "Peruttu",
    "canceled": "Peruttu",
    "pending": "Odottaa",
    "pending_signature": "Odottaa allekirjoitusta",
    "paid": "Maksettu",
    "overdue": "Erääntynyt",
    "open": "Avoin",
    "new": "Uusi",
    "in_progress": "Työn alla",
    "waiting": "Odottaa",
    "resolved": "Ratkaistu",
    "confirmed": "Vahvistettu",
    "checked_in": "Saapunut",
    "checked_out": "Lähtenyt",
    "failed": "Epäonnistui",
    "failure": "Epäonnistui",
    "success": "Onnistui",
    "sent": "Lähetetty",
    "sending": "Lähetetään",
    "delivered": "Toimitettu",
    "succeeded": "Onnistui",
    "refunded": "Hyvitetty",
    "partial_refund": "Osittain hyvitetty",
    "partially_refunded": "Osittain hyvitetty",
    "void": "Mitätöity",
    "manual": "Manuaalinen",
    "stripe": "Stripe",
    "paytrail": "Paytrail",
    "expired": "Vanhentunut",
    "operational": "Toiminnassa",
    "degraded": "Heikentynyt",
    "outage": "Käyttökatko",
    "maintenance": "Huolto",
}

PRIORITY_LABELS_FI = {
    "low": "Matala",
    "normal": "Normaali",
    "medium": "Normaali",
    "high": "Korkea",
    "urgent": "Kiireellinen",
}

UNIT_AVAILABILITY_LABELS_FI = {
    "free": "Vapaa",
    "reserved": "Varattu",
    "transition": "Vaihtopäivä",
    "maintenance": "Huolto",
    "blocked": "Estetty",
}


def status_label(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return STATUS_LABELS_FI.get(normalized, value or "-")


def priority_label(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return PRIORITY_LABELS_FI.get(normalized, "-")


def availability_label(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return UNIT_AVAILABILITY_LABELS_FI.get(normalized, value or "-")


def bool_label(value: bool) -> str:
    return "Kyllä" if value else "Ei"
