from flask import Blueprint, current_app, g, request

api_bp = Blueprint("api", __name__)

# Routes are attached via import side-effects after the blueprint exists.
from app.api import (  # noqa: E402
    docs,  # noqa: E402,F401
    routes,  # noqa: E402,F401
)

from app.api.auth import ensure_api_key_loaded, is_unit_calendar_ics_request_path  # noqa: E402
from app.api.schemas import json_error  # noqa: E402

_SCOPE_WHITELIST_PATHS = frozenset({"/api/v1/health", "/api/v1/me"})


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

    if not hasattr(view_func, "_required_scope"):
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

    err = ensure_api_key_loaded()
    if err is not None:
        return err

    if not hasattr(g, "api_key") or g.api_key is None:
        return json_error("unauthorized", "API key authentication is required.", status=401)

    return None
