from flask import Blueprint, request
from flask_login import current_user

admin_bp = Blueprint("admin", __name__)


@admin_bp.context_processor
def _inject_admin_navigation():
    from app.admin.navigation import build_nav_context

    user = current_user
    try:
        if not user.is_authenticated:
            user = None
        else:
            _ = user.role
    except Exception:
        user = None
    return build_nav_context(endpoint=request.endpoint or "", user=user)


# Routes are attached via import side-effects after the blueprint exists.
from app.admin import routes  # noqa: E402,F401
