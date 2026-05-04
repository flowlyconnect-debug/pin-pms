from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import current_app, g, has_request_context
from sqlalchemy.exc import IntegrityError

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.extensions import db
from app.idempotency.models import IdempotencyKey

logger = logging.getLogger(__name__)


class IdempotencyKeyConflict(Exception):
    """Raised when an active idempotency key is reused with a different request body."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_expires_at(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _resolve_organization_id() -> int | None:
    if not has_request_context():
        return None
    api_key = getattr(g, "api_key", None)
    if api_key is not None:
        oid = getattr(api_key, "organization_id", None)
        if oid is not None:
            return int(oid)
    try:
        from flask_login import current_user

        if getattr(current_user, "is_authenticated", False):
            oid = getattr(current_user, "organization_id", None)
            if oid is not None:
                return int(oid)
    except Exception:  # noqa: BLE001 — missing login context is fine.
        return None
    return None


def get_or_create(
    key: str,
    endpoint: str,
    request_hash: str,
    *,
    organization_id: int | None = None,
) -> tuple[IdempotencyKey, bool]:
    """Return ``(row, created)``. ``created`` is False when replaying the same request hash."""

    ttl = int(current_app.config.get("IDEMPOTENCY_KEY_TTL_SECONDS", 86400))
    org_id = organization_id if organization_id is not None else _resolve_organization_id()

    for _ in range(8):
        now = _now()
        row = IdempotencyKey.query.filter_by(key=key).one_or_none()
        if row is not None:
            exp = _normalize_expires_at(row.expires_at)
            if exp > now:
                if row.request_hash == request_hash:
                    return row, False
                audit_record(
                    "idempotency.conflict",
                    status=AuditStatus.FAILURE,
                    target_type="idempotency_key",
                    target_id=row.id,
                    metadata={"endpoint": endpoint, "status": "failure"},
                )
                raise IdempotencyKeyConflict()
            db.session.delete(row)
            db.session.flush()

        new_row = IdempotencyKey(
            key=key,
            endpoint=endpoint,
            request_hash=request_hash,
            organization_id=org_id,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
        db.session.add(new_row)
        try:
            db.session.flush()
            return new_row, True
        except IntegrityError:
            db.session.rollback()
            continue

    raise RuntimeError("Could not allocate idempotency key row")


def should_cache(status: int) -> bool:
    if status >= 500:
        return False
    if 400 <= status < 500 and status != 422:
        return False
    return True


_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "client_secret",
    "bearer",
    "signature",
)


def _redact_for_cache(obj: Any) -> Any:
    """Strip high-risk nested keys from structures we persist for idempotent replay."""

    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if any(part in lk for part in _SENSITIVE_KEY_FRAGMENTS):
                out[str(k)] = "[REDACTED]"
            else:
                out[str(k)] = _redact_for_cache(v)
        return out
    if isinstance(obj, list):
        return [_redact_for_cache(v) for v in obj]
    return obj


def normalize_response_body(body: Any) -> str:
    if body is None:
        return ""
    if isinstance(body, (dict, list)):
        return json.dumps(
            _redact_for_cache(body), ensure_ascii=False, separators=(",", ":")
        )
    if isinstance(body, str):
        return body
    if hasattr(body, "get_json"):
        try:
            data = body.get_json(silent=True)
            if data is not None:
                return json.dumps(
                    _redact_for_cache(data),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
        except Exception:  # noqa: BLE001
            pass
    if hasattr(body, "get_data"):
        try:
            return body.get_data(as_text=True) or ""
        except Exception:  # noqa: BLE001
            return ""
    return str(body)


def record_response(row: IdempotencyKey, status: int, body: Any) -> None:
    if not should_cache(status):
        return
    body_text = normalize_response_body(body)
    raw = body_text.encode("utf-8")
    if len(raw) > 65536:
        body_text = raw[:65536].decode("utf-8", errors="ignore")

    row.response_status = status
    row.response_body = body_text
    db.session.commit()


def prune_expired() -> int:
    now = _now()
    deleted = (
        IdempotencyKey.query.filter(IdempotencyKey.expires_at < now).delete(synchronize_session=False)
    )
    db.session.commit()
    return int(deleted or 0)
