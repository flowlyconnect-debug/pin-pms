from flask import Blueprint

backups_bp = Blueprint("backups", __name__)
backups_admin_bp = Blueprint("backups_admin", __name__)

# Attach backup admin routes after blueprint creation.
from app.backups import routes  # noqa: E402,F401
