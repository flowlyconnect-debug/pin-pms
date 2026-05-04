"""Default settings shipped with the application.

These are inserted by the ``add_settings_table`` migration and re-checked at
startup by :func:`app.settings.services.ensure_seed_settings`. Existing rows
are never overwritten — admin edits are preserved.

Keep this list short and generic. PMS-specific values (room counts, default
nightly rate, business hours) belong with the business logic that actually
consumes them; this file is only for foundational settings the framework
itself reads.
"""

from __future__ import annotations

from typing import TypedDict


class SettingSeed(TypedDict):
    key: str
    value: str | None
    type: str
    description: str
    is_secret: bool


SEED_SETTINGS: list[SettingSeed] = [
    {
        "key": "company_name",
        "value": "Pin PMS",
        "type": "string",
        "description": "Display name used in emails, page titles, and the admin UI.",
        "is_secret": False,
    },
    {
        "key": "default_locale",
        "value": "fi-FI",
        "type": "string",
        "description": "Default locale for new users (BCP-47 tag).",
        "is_secret": False,
    },
    {
        "key": "default_timezone",
        "value": "Europe/Helsinki",
        "type": "string",
        "description": "Default IANA timezone for new users.",
        "is_secret": False,
    },
    {
        "key": "billing.default_vat_rate",
        "value": "24.00",
        "type": "decimal",
        "description": "Oletus-ALV-kanta laskuille (%)",
        "is_secret": False,
    },
]
