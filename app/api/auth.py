"""API-key authentication helpers for ``/api/v1`` routes."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from functools import wraps
from typing import Callable, Optional

from flask import after_this_request, g, request

from app.api.models import ApiKey
from app.api.schemas import json_error
from app.api.services import record_api_key_usage
from app.extensions import db

logger = logging.getLogger(__name__)

_UNIT_CALENDAR_ICS_PATH = re.compile(r"^/api/v1/units/\d+/calendar\.ics$")


def is_unit_calendar_ics_request_path(path: str) -> bool:
    """True for the signed-token iCal export URL (no API key required)."""

    return bool(path and _UNIT_CALENDAR_ICS_PATH.match(path))


def _extract_raw_key() -> str | None:
    """Return the API key supplied in the request, or ``None`` if absent.

    Accepts either header per the project brief (section 6):

      * ``Authorization: Bearer <key>``
      * ``X-API-Key: <key>``
    """

    auth_header = request.headers.get("Authorization", "")
    if auth_header:
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()

    x_api_key = request.headers.get("X-API-Key", "").strip()
    if x_api_key:
        return x_api_key

    return None


def ensure_api_key_loaded() -> Optional[tuple]:
    """Validate ``Authorization`` / ``X-API-Key``, populate ``g.api_key``, or return a JSON error.

    Idempotent per request: if ``g.api_key`` is already set, returns ``None``.
    """

    if getattr(g, "api_key", None) is not None:
        return None

    raw_key = _extract_raw_key()
    if not raw_key:
        return json_error(
            "unauthorized",
            "API key is required. Provide it via the 'Authorization: Bearer "
            "<key>' or 'X-API-Key: <key>' header.",
            status=401,
        )

    api_key = ApiKey.find_active_by_raw_key(raw_key)
    if api_key is None:
        return json_error(
            "unauthorized",
            "Invalid, disabled, or expired API key.",
            status=401,
        )

    g.api_key = api_key
    g.api_organization = api_key.organization
    g.api_user = api_key.user
    api_key.last_used_at = datetime.now(timezone.utc)

    if not getattr(g, "_api_key_usage_scheduled", False):
        g._api_key_usage_scheduled = True

        @after_this_request
        def _record_usage(response):
            try:
                ip = (
                    request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                    or request.remote_addr
                )
                record_api_key_usage(
                    api_key_id=api_key.id,
                    endpoint=request.path,
                    status_code=response.status_code,
                    ip=ip,
                    user_agent=request.headers.get("User-Agent"),
                )
                db.session.commit()
            except Exception:  # noqa: BLE001
                db.session.rollback()
                logger.exception("Failed to record api key usage for key_id=%s", api_key.id)
            return response

    return None


def require_api_key(view_func: Callable):
    """Decorator that enforces API-key auth on a route.

    On success stashes the authenticated ``ApiKey`` on ``flask.g`` as
    ``g.api_key`` so handlers can access the owning user and organization.
    On failure returns a uniform JSON error.
    """

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        err = ensure_api_key_loaded()
        if err is not None:
            return err
        return view_func(*args, **kwargs)

    if hasattr(view_func, "_required_scope"):
        wrapper._required_scope = view_func._required_scope
    return wrapper


def _scope_matches(*, assigned_scope: str, required_scope: str) -> bool:
    if assigned_scope == required_scope:
        return True
    if assigned_scope.endswith(":*"):
        return required_scope.startswith(assigned_scope[:-1])
    return False


def scope_required(scope: str):
    """Decorator that enforces a required API key scope for a route."""

    required_scope = (scope or "").strip()

    def decorator(view_func: Callable):
        view_func._required_scope = required_scope

        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if (
                request.endpoint == "api.export_unit_calendar_ics"
                and required_scope == "properties:read"
            ):
                from app.integrations.ical.service import IcalService

                unit_id = kwargs.get("unit_id")
                if unit_id is not None:
                    token = (request.args.get("token") or "").strip()
                    if token:
                        if IcalService().verify_unit_token(unit_id=unit_id, token=token):
                            return view_func(*args, **kwargs)
                        return json_error("forbidden", "Invalid calendar token.", status=403)

            err = ensure_api_key_loaded()
            if err is not None:
                return err

            api_key = getattr(g, "api_key", None)
            if api_key is None:
                return json_error("unauthorized", "API key authentication is required.", status=401)
            scopes = api_key.scope_list
            if not scopes:
                return json_error(
                    "forbidden",
                    "API key has no scopes assigned; assign at least one scope to use this endpoint.",
                    status=403,
                )
            if required_scope and not any(
                _scope_matches(assigned_scope=s, required_scope=required_scope) for s in scopes
            ):
                return json_error(
                    "forbidden",
                    f"Missing required scope: {required_scope}",
                    status=403,
                )
            return view_func(*args, **kwargs)

        wrapper._required_scope = required_scope
        return wrapper

    return decorator
