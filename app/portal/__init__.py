from flask import Blueprint

portal_bp = Blueprint("portal", __name__, template_folder="../templates")

from app.portal import routes  # noqa: E402,F401

