from flask import Blueprint

backups_bp = Blueprint("backups", __name__)
from .routes import backups_admin_bp as backups_admin_bp
