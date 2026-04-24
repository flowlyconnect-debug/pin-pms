from flask import Blueprint

core_bp = Blueprint("core", __name__)


@core_bp.get("/health")
def health():
    return {"status": "ok"}, 200
