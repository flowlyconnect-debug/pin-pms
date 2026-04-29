from flask import Blueprint

api_bp = Blueprint("api", __name__)

# Routes are attached via import side-effects after the blueprint exists.
from app.api import (  # noqa: E402
    docs,  # noqa: E402,F401
    routes,  # noqa: E402,F401
)
