"""API-key authentication helpers for ``/api/v1`` routes."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import g, request

from app.api.models import ApiKey
from app.api.schemas import json_error
from app.extensions import db


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

        api_key.touch()
        db.session.commit()

        g.api_key = api_key
        g.api_organization = api_key.organization
        g.api_user = api_key.user
        return view_func(*args, **kwargs)

    return wrapper
