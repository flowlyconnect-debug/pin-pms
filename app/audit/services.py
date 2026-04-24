"""Service layer for audit logging.

The single public function, :func:`record`, writes one row to ``audit_logs``
and flushes it immediately. It is safe to call from request handlers, CLI
commands, and background code: when a Flask request/login context is present
it is read automatically, otherwise the missing fields are simply left blank.

Design notes
------------

* ``record`` *flushes* but does not *commit*. The caller's existing
  transaction (e.g. a login view) is responsible for the commit, which keeps
  the audit insert atomic with the action being audited. If the caller
  explicitly passes ``commit=True`` the function will commit on its own —
  useful from CLI commands that otherwise would not call ``db.session.commit``
  after the audited action.
* ``record`` never raises. If the audit insert itself fails for any reason,
  the error is logged and swallowed so the audited operation is not lost
  because of an observability hiccup.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from app.audit.models import ActorType, AuditLog, AuditStatus
from app.extensions import db

logger = logging.getLogger(__name__)


def _resolve_actor() -> tuple[str, Optional[int], Optional[str], Optional[int]]:
    """Best-effort resolution of actor fields from the current Flask context.

    Returns ``(actor_type, actor_id, actor_email, organization_id)``. Any
    missing value is returned as ``None``.
    """

    # Imports are local to avoid pulling Flask during module import when the
    # audit service is used from non-web contexts (tests, migrations, CLI).
    try:
        from flask import g, has_app_context, has_request_context
    except ImportError:
        return ActorType.SYSTEM, None, None, None

    actor_type = ActorType.SYSTEM
    actor_id: Optional[int] = None
    actor_email: Optional[str] = None
    organization_id: Optional[int] = None

    if not has_app_context():
        return actor_type, actor_id, actor_email, organization_id

    # 1) API-key context wins over user session — an API caller is unambiguously
    #    the actor for the request it made even if a user session is also
    #    somehow present.
    api_key = getattr(g, "api_key", None)
    if api_key is not None:
        actor_type = ActorType.API_KEY
        actor_id = getattr(api_key, "id", None)
        owner = getattr(api_key, "user", None)
        actor_email = getattr(owner, "email", None) if owner is not None else None
        organization_id = getattr(api_key, "organization_id", None)
        return actor_type, actor_id, actor_email, organization_id

    # 2) Logged-in user via Flask-Login.
    if has_request_context():
        try:
            from flask_login import current_user  # Imported lazily.
        except ImportError:
            current_user = None  # type: ignore[assignment]

        if current_user is not None and getattr(current_user, "is_authenticated", False):
            actor_type = ActorType.USER
            actor_id = getattr(current_user, "id", None)
            actor_email = getattr(current_user, "email", None)
            organization_id = getattr(current_user, "organization_id", None)
            return actor_type, actor_id, actor_email, organization_id

        # 3) No authenticated actor, but we are still inside a request →
        #    anonymous (e.g. failed login attempt).
        return ActorType.ANONYMOUS, None, None, None

    return ActorType.SYSTEM, None, None, None


def _resolve_request_metadata() -> tuple[Optional[str], Optional[str]]:
    """Return ``(ip_address, user_agent)`` from the active request, if any."""

    try:
        from flask import has_request_context, request
    except ImportError:
        return None, None

    if not has_request_context():
        return None, None

    # Respect proxy-provided addresses when the app is behind one.
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.remote_addr or None)

    user_agent = request.headers.get("User-Agent", None)
    if user_agent is not None and len(user_agent) > 512:
        user_agent = user_agent[:512]

    return ip, user_agent


def record(
    action: str,
    *,
    status: Optional[str] = AuditStatus.SUCCESS,
    actor_type: Optional[str] = None,
    actor_id: Optional[int] = None,
    actor_email: Optional[str] = None,
    organization_id: Optional[int] = None,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    context: Optional[Mapping[str, Any]] = None,
    commit: bool = False,
) -> Optional[AuditLog]:
    """Insert an audit row. Safe to call from anywhere.

    Any ``actor_*``/``organization_id`` argument that is left as ``None`` is
    resolved from the current Flask context (API key on ``g``, Flask-Login
    ``current_user``, or anonymous request). Explicit values always win so
    CLI commands can audit a user they are creating even though the CLI
    itself has no logged-in actor.
    """

    try:
        resolved_type, resolved_id, resolved_email, resolved_org = _resolve_actor()
        ip, user_agent = _resolve_request_metadata()

        entry = AuditLog(
            action=action,
            status=status,
            actor_type=actor_type or resolved_type,
            actor_id=actor_id if actor_id is not None else resolved_id,
            actor_email=actor_email or resolved_email,
            organization_id=(
                organization_id if organization_id is not None else resolved_org
            ),
            target_type=target_type,
            target_id=target_id,
            ip_address=ip,
            user_agent=user_agent,
            context=dict(context) if context else None,
        )

        db.session.add(entry)
        db.session.flush()

        if commit:
            db.session.commit()

        return entry
    except Exception:  # noqa: BLE001 — audit must never break the caller.
        logger.exception("Failed to record audit log for action=%s", action)
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None
