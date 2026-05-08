from flask import Blueprint

from .routes import backups_admin_bp as backups_admin_bp

backups_bp = Blueprint("backups", __name__)
