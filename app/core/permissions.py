"""Role + tenant permission helpers — project brief section 12.

Centralises checks like "is the current user an admin or above?" so call
sites do not duplicate the role-string comparison logic. The existing
2FA / superadmin guards live in :mod:`app.auth.routes`; the helpers here
are small functions that any module can import without pulling Flask in.
"""
from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from app.users.models import UserRole


# ---------------------------------------------------------------------------
# Pure helpers — no Flask context required.
# ---------------------------------------------------------------------------


def is_admin(role: str | None) -> bool:
    """Return True for ``admin`` or ``superadmin`` role values."""

    return role in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}


def is_superadmin(role: str | None) -> bool:
    return role == UserRole.SUPERADMIN.value


def can_access_organization(actor_org_id: int | None, target_org_id: int | None) -> bool:
    """Default tenant rule: same organisation only.

    Future cross-tenant overrides for superadmins should be added here so
    routes do not duplicate the rule.
    """

    if actor_org_id is None or target_org_id is None:
        return False
    return int(actor_org_id) == int(target_org_id)


# ---------------------------------------------------------------------------
# Decorators — Flask-bound. Used by admin / management routes.
# ---------------------------------------------------------------------------


def require_admin(view_func):
    """Allow only ``admin`` or ``superadmin`` users (no 2FA gate)."""

    @wraps(view_func)
    @login_required
    def wrapper(*args, **kwargs):
        if not is_admin(getattr(current_user, "role", None)):
            abort(403)
        return view_func(*args, **kwargs)

    return wrapper


def require_superadmin(view_func):
    """Allow only ``superadmin`` users (no 2FA gate; use the auth-side
    decorator if 2FA is also needed)."""

    @wraps(view_func)
    @login_required
    def wrapper(*args, **kwargs):
        if not is_superadmin(getattr(current_user, "role", None)):
            abort(403)
        return view_func(*args, **kwargs)

    return wrapper
