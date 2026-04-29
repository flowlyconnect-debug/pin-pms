from flask import Blueprint

owner_portal_bp = Blueprint("owner_portal", __name__, template_folder="../templates")

from app.owner_portal import routes  # noqa: E402,F401
