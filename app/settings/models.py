"""Settings table — exact schema from project brief section 9.

Fields
------

* ``key``         — stable, snake_case identifier (e.g. ``company_name``).
* ``value``       — the raw stored value as text. Typed values (int, bool,
                    json) are serialised on write and deserialised on read by
                    the service layer; ``value`` itself is always text or
                    NULL so a partial migration can never corrupt the column.
* ``type``        — one of ``SettingType.ALL``. Determines how ``value`` is
                    encoded and decoded.
* ``description`` — admin-facing help text.
* ``is_secret``   — when true, the value is masked in the admin UI and never
                    appears in audit log context.
* ``updated_by``  — FK to the user who last changed the setting. ``SET NULL``
                    on user delete so historical settings stay readable.
* ``updated_at``  — auto-touched on every write.

Direct queries against this table are intentionally discouraged: every
read/write should go through :mod:`app.settings.services`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


class SettingType:
    STRING = "string"
    INT = "int"
    BOOL = "bool"
    JSON = "json"

    ALL = (STRING, INT, BOOL, JSON)


class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(128), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)
    type = db.Column(db.String(16), nullable=False, default=SettingType.STRING)
    description = db.Column(db.String(255), nullable=False, default="")
    is_secret = db.Column(db.Boolean, nullable=False, default=False)
    updated_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic only
        return f"<Setting {self.key} type={self.type}>"
