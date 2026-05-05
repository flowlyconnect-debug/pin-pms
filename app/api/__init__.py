from flask import Blueprint, current_app, request

api_bp = Blueprint("api", __name__)

# Routes are attached via import side-effects after the blueprint exists.
from app.api import (  # noqa: E402
    docs,  # noqa: E402,F401
    payments,  # noqa: E402,F401
    routes,  # noqa: E402,F401
)

from app.api.auth import is_unit_calendar_ics_request_path  # noqa: E402
from app.api.schemas import json_error  # noqa: E402

_SCOPE_WHITELIST_PATHS = frozenset({"/api/v1/health", "/api/v1/me"})


def _lookup_required_scope(view_func):
    """Find ``_required_scope`` set by ``@scope_required`` through Flask/route wrappers."""

    seen: set[int] = set()
    func = view_func
    while func is not None:
        oid = id(func)
        if oid in seen:
            break
        seen.add(oid)
        scope = getattr(func, "_required_scope", None)
        if isinstance(scope, str) and scope.strip():
            return scope.strip()
        func = getattr(func, "__wrapped__", None)
    return None


@api_bp.before_request
def enforce_api_v1_scope_contract():
    """Fail closed: every ``/api/v1`` handler must declare a required scope (except whitelist)."""

    if request.path in _SCOPE_WHITELIST_PATHS:
        return None

    endpoint = request.endpoint
    if endpoint is None or not str(endpoint).startswith("api."):
        return None

    view_func = current_app.view_functions.get(endpoint)
    if view_func is None:
        return None

    if _lookup_required_scope(view_func) is None:
        current_app.logger.error(
            "endpoint missing @scope_required",
            extra={
                "endpoint": endpoint,
                "path": request.path,
                "method": request.method,
            },
        )
        return json_error(
            "internal_error",
            "Endpoint configuration error.",
            status=500,
        )

    if is_unit_calendar_ics_request_path(request.path):
        return None

    # Auth + scope enforcement stay in ``@require_api_key`` / ``@scope_required``.
    # Loading the key here duplicated work and could leave ``g.api_key`` expired
    # before the view wrappers ran (SQLAlchemy session edge cases in tests).

    return None
