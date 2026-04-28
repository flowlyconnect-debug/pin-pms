"""API-key authentication helpers for ``/api/v1`` routes."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from datetime import datetime, timezone
import logging

from flask import after_this_request, g, request

from app.api.models import ApiKey
from app.api.services import record_api_key_usage
from app.api.schemas import json_error
from app.extensions import db

logger = logging.getLogger(__name__)


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


def require_api_key(view_func: Callable):
    """Decorator that enforces API-key auth on a route.

    On success stashes the authenticated ``ApiKey`` on ``flask.g`` as
    ``g.api_key`` so handlers can access the owning user and organization.
    On failure returns a uniform JSON error.
    """

    @wraps(view_func)
    def wrapper(*args, **kwargs):
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

        @after_this_request
        def _record_usage(response):
            try:
                ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr
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

        return view_func(*args, **kwargs)

    return wrapper
