from flask import Blueprint

admin_bp = Blueprint("admin", __name__)

# Routes are attached via import side-effects after the blueprint exists.
from app.admin import routes  # noqa: E402,F401
