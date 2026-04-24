from flask import Blueprint, render_template
from flask_login import current_user

core_bp = Blueprint("core", __name__)


@core_bp.get("/")
def index():
    return render_template("index.html", current_user=current_user)


@core_bp.get("/health")
def health():
    return {"status": "ok"}, 200
