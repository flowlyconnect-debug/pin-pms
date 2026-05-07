"""Centralised settings service.

The single rule: **no other module talks to the ``settings`` table directly**.
Every read goes through :func:`get` (or :func:`get_all` for admin views), and
every write goes through :func:`set_value`. Keeping that funnel narrow gives
us one place to add caching, audit hooks, and secret masking.

Typed values
------------

The DB stores ``value`` as text; ``type`` decides how :func:`get` decodes it:

* ``string`` → ``str`` (or empty string if ``value`` is NULL)
* ``int``    → ``int``
* ``bool``   → ``bool``  (``"true"`` / ``"false"``)
* ``json``   → parsed via :func:`json.loads`

Writers pass native Python values to :func:`set_value`; the encoder picks the
right serialisation. A type mismatch raises :class:`SettingValueError`.

Secrets
-------

When ``is_secret=True`` the row is still readable through :func:`get`, but
the admin UI and audit log only ever see the masked output of
:func:`mask_for_display`. Audit context for ``settings.update`` never
includes raw secret values — only redaction flags and row metadata.

Per-request cache
-----------------

Reads are memoised on ``flask.g`` so a single request that reads
``company_name`` ten times only hits the DB once. The cache is invalidated
inside :func:`set_value` so a write within the same request reflects
immediately.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from flask import g, has_request_context

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.extensions import db
from app.settings.models import Setting, SettingType

logger = logging.getLogger(__name__)

_CACHE_KEY = "_settings_cache"
_MASK = "••••••"


class SettingValueError(ValueError):
    """Raised when ``value`` cannot be coerced to the declared ``type``."""


class SettingNotFound(LookupError):
    """Raised by ``require`` when a setting key does not exist."""


# ---------------------------------------------------------------------------
# Encoding / decoding
# ---------------------------------------------------------------------------


def _decode(stored: Optional[str], type_: str) -> Any:
    """Turn the raw text in the column into a native Python value."""

    if stored is None:
        # NULL means "unset". Match the natural empty for each type.
        return {"string": "", "int": 0, "bool": False, "json": None, "decimal": Decimal("0.00")}.get(
            type_, ""
        )

    if type_ == SettingType.STRING:
        return stored
    if type_ == SettingType.INT:
        try:
            return int(stored)
        except ValueError as err:
            raise SettingValueError(f"Setting value is not a valid int: {stored!r}") from err
    if type_ == SettingType.BOOL:
        normalized = stored.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
        raise SettingValueError(f"Setting value is not a valid bool: {stored!r}")
    if type_ == SettingType.JSON:
        try:
            return json.loads(stored)
        except json.JSONDecodeError as err:
            raise SettingValueError(f"Setting value is not valid JSON: {err}") from err
    if type_ == SettingType.DECIMAL:
        try:
            return Decimal(str(stored).strip()).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError) as err:
            raise SettingValueError(f"Setting value is not a valid decimal: {stored!r}") from err

    raise SettingValueError(f"Unknown setting type: {type_!r}")


def _encode(value: Any, type_: str) -> Optional[str]:
    """Serialise a native Python value to the stored text representation."""

    if type_ not in SettingType.ALL:
        raise SettingValueError(f"Unknown setting type: {type_!r}")

    if value is None:
        return None

    if type_ == SettingType.STRING:
        return str(value)
    if type_ == SettingType.INT:
        if isinstance(value, bool):  # bool is a subclass of int — reject explicitly
            raise SettingValueError("int setting cannot accept a bool value")
        try:
            return str(int(value))
        except (TypeError, ValueError) as err:
            raise SettingValueError(f"Cannot encode {value!r} as int") from err
    if type_ == SettingType.BOOL:
        if isinstance(value, bool):
            return "true" if value else "false"
        # Accept the same strings _decode does.
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return "true"
            if normalized in {"false", "0", "no", "off", ""}:
                return "false"
        raise SettingValueError(f"Cannot encode {value!r} as bool")
    if type_ == SettingType.JSON:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as err:
            raise SettingValueError(f"Cannot encode {value!r} as JSON") from err
    if type_ == SettingType.DECIMAL:
        try:
            dec = Decimal(str(value)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError) as err:
            raise SettingValueError(f"Cannot encode {value!r} as decimal") from err
        return format(dec, "f")

    raise SettingValueError(f"Unhandled setting type: {type_!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache() -> dict[str, Any]:
    if not has_request_context():
        return {}
    if not hasattr(g, _CACHE_KEY):
        setattr(g, _CACHE_KEY, {})
    return getattr(g, _CACHE_KEY)


def _cache_invalidate(key: str) -> None:
    if has_request_context() and hasattr(g, _CACHE_KEY):
        getattr(g, _CACHE_KEY).pop(key, None)


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------


def get(key: str, default: Any = None) -> Any:
    """Return the typed value for ``key``, or ``default`` if missing."""

    cache = _cache()
    if key in cache:
        return cache[key]

    row: Optional[Setting] = Setting.query.filter_by(key=key).first()
    if row is None:
        # Don't cache misses — a setting could be created mid-request.
        return default

    value = _decode(row.value, row.type)
    cache[key] = value
    return value


def require(key: str) -> Any:
    """Like :func:`get`, but raises :class:`SettingNotFound` if missing."""

    sentinel = object()
    value = get(key, default=sentinel)
    if value is sentinel:
        raise SettingNotFound(f"Setting {key!r} is not defined.")
    return value


def get_all(*, include_secrets: bool = False) -> list[Setting]:
    """Return every setting row, ordered by key — for admin listings.

    Pass ``include_secrets=False`` (the default) when rendering an admin list
    so secret values never appear in HTML; the model objects are returned as
    is, but callers should pair this with :func:`mask_for_display`.
    """

    rows = Setting.query.order_by(Setting.key.asc()).all()
    if include_secrets:
        return rows
    return rows  # masking is the template's job; the rows themselves are unchanged


def find(key: str) -> Optional[Setting]:
    """Return the raw row for ``key`` (admin edit views) or ``None``."""

    return Setting.query.filter_by(key=key).first()


# ---------------------------------------------------------------------------
# Public write API
# ---------------------------------------------------------------------------


def set_value(
    key: str,
    value: Any,
    *,
    type_: Optional[str] = None,
    description: Optional[str] = None,
    is_secret: Optional[bool] = None,
    actor_user_id: Optional[int] = None,
) -> Setting:
    """Upsert a setting and audit the change.

    Behaviour:

    * If ``key`` exists, the row is updated in place. Fields not passed retain
      their existing values.
    * If ``key`` does not exist, a new row is created — ``type_`` must be
      supplied in that case.
    * The encoded value is written to ``value``, ``updated_by`` is set to
      ``actor_user_id``, and ``updated_at`` is auto-touched by the model.
    * A ``settings.update`` audit row is committed with structured context
      (init template §11) — **never** raw values for secret rows.

    Raises :class:`SettingValueError` if the value cannot be encoded under the
    declared type.
    """

    row = Setting.query.filter_by(key=key).first()

    # Snapshot the *previous* state before mutating so the audit row carries
    # before/after context. For ``is_secret`` rows the actual values are
    # masked out — only the fact that "value changed" is preserved.
    if row is None:
        is_create = True
        previous_value: Any = None
        previous_is_secret = False
    else:
        is_create = False
        previous_value = row.value
        previous_is_secret = bool(row.is_secret)

    if row is None:
        if type_ is None:
            raise SettingValueError(f"Cannot create setting {key!r} without a type.")
        if type_ not in SettingType.ALL:
            raise SettingValueError(f"Unknown setting type: {type_!r}")

        row = Setting(
            key=key,
            type=type_,
            description=description or "",
            is_secret=bool(is_secret) if is_secret is not None else False,
        )
        db.session.add(row)
    else:
        if type_ is not None and type_ != row.type:
            if type_ not in SettingType.ALL:
                raise SettingValueError(f"Unknown setting type: {type_!r}")
            row.type = type_
        if description is not None:
            row.description = description
        if is_secret is not None:
            row.is_secret = bool(is_secret)

    new_encoded = _encode(value, row.type)
    row.value = new_encoded
    row.updated_by = actor_user_id

    db.session.commit()
    _cache_invalidate(key)

    value_changed = True
    if not is_create:
        value_changed = previous_value != new_encoded

    audit_context: dict[str, Any] = {
        "key": row.key,
        "type": row.type,
        "is_secret": bool(row.is_secret),
        "action": "create" if is_create else "update",
        "old_value_redacted": bool(previous_is_secret),
        "new_value_redacted": bool(row.is_secret),
    }
    if (row.is_secret or previous_is_secret) and value_changed:
        audit_context["value_changed"] = True

    audit_record(
        "settings.update",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        target_type="setting",
        target_id=row.id,
        context=audit_context,
        commit=True,
    )
    return row


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def mask_for_display(setting: Setting) -> str:
    """Return a string safe to render in HTML for ``setting``.

    * Secret rows always return a fixed mask, regardless of the actual value
      length, to avoid leaking even the magnitude of a secret.
    * Non-secret values are decoded and stringified. JSON values are
      pretty-printed in a single line so the admin list stays compact.
    """

    if setting.is_secret:
        return _MASK if setting.value else "—"

    try:
        value = _decode(setting.value, setting.type)
    except SettingValueError:
        return f"<invalid {setting.type}>"

    if setting.type == SettingType.JSON:
        return json.dumps(value, ensure_ascii=False)
    if setting.type == SettingType.BOOL:
        return "true" if value else "false"
    if setting.type == SettingType.DECIMAL:
        return str(value)
    return str(value)


# ---------------------------------------------------------------------------
# Seed reconciliation (CLI / startup)
# ---------------------------------------------------------------------------


def ensure_seed_settings() -> list[str]:
    """Insert any seed rows that are missing. Returns the inserted keys.

    Existing rows are never overwritten, so admin edits survive re-runs.
    """

    from app.settings.seed_data import SEED_SETTINGS

    existing = {row.key for row in Setting.query.all()}
    inserted: list[str] = []

    for s in SEED_SETTINGS:
        if s["key"] in existing:
            continue
        row = Setting(
            key=s["key"],
            value=s["value"],
            type=s["type"],
            description=s["description"],
            is_secret=s["is_secret"],
        )
        db.session.add(row)
        inserted.append(s["key"])

    if inserted:
        db.session.commit()
        logger.info("Seeded missing settings: %s", inserted)
    return inserted
