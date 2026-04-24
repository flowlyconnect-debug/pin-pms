from flask import Flask

from app.config import config_by_name
from app.extensions import db, migrate


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)

    selected_config = config_name or "default"
    app.config.from_object(config_by_name[selected_config])

    if selected_config == "production" and not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set in production.")

    db.init_app(app)
    migrate.init_app(app, db)

    register_blueprints(app)

    return app


def register_blueprints(app: Flask) -> None:
    from app.admin import admin_bp
    from app.api import api_bp
    from app.auth import auth_bp
    from app.backups import backups_bp
    from app.core import core_bp
    from app.email import email_bp
    from app.users import users_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(email_bp, url_prefix="/email")
    app.register_blueprint(backups_bp, url_prefix="/backups")
