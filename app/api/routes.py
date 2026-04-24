"""Public API routes served under ``/api/v1``.

Minimum surface required by the project brief (section 6):

* ``GET /api/v1/health`` — unauthenticated liveness check.
* ``GET /api/v1/me``     — returns the context of the API key making the call.
"""
from __future__ import annotations

from flask import g

from app.api import api_bp
from app.api.auth import require_api_key
from app.api.schemas import json_ok


@api_bp.get("/health")
def api_health():
    """Liveness probe. Intentionally open — does not expose any tenant data."""

    return json_ok({"status": "ok"})


@api_bp.get("/me")
@require_api_key
def api_me():
    """Return who the calling API key belongs to."""

    api_key = g.api_key

    user_payload = None
    if api_key.user is not None:
        user_payload = {
            "id": api_key.user.id,
            "email": api_key.user.email,
            "role": api_key.user.role,
        }

    data = {
        "api_key": {
            "id": api_key.id,
            "name": api_key.name,
            "prefix": api_key.key_prefix,
            "scopes": api_key.scope_list,
            "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
            "last_used_at": (
                api_key.last_used_at.isoformat() if api_key.last_used_at else None
            ),
        },
        "organization": {
            "id": api_key.organization_id,
            "name": api_key.organization.name,
        },
        "user": user_payload,
    }
    return json_ok(data)
