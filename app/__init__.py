from flask import Flask
from flask import redirect, request, session, url_for
from flask_login import current_user

from app.cli import register_cli_commands
from app.config import config_by_name
from app.extensions import db, login_manager, migrate


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)

    selected_config = config_name or "default"
    app.config.from_object(config_by_name[selected_config])

    if selected_config == "production" and not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set in production.")

    db.init_app(app)
    register_models()
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_message = "Please log in to continue."

    register_blueprints(app)
    register_cli_commands(app)
    register_security_guards(app)

    return app


def register_models() -> None:
    # Ensure model metadata is loaded before Flask-Migrate autogenerate.
    from app.organizations.models import Organization
    from app.users.models import User

    _ = (Organization, User)


@login_manager.user_loader
def load_user(user_id: str):
    from app.users.models import User

    return User.query.get(int(user_id))


def register_blueprints(app: Flask) -> None:
    from app.admin import admin_bp
    from app.api import api_bp
    from app.auth import auth_bp
    from app.backups import backups_bp
    from app.core import core_bp
    from app.email import email_bp
    from app.users import users_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(email_bp, url_prefix="/email")
    app.register_blueprint(backups_bp, url_prefix="/backups")


def register_security_guards(app: Flask) -> None:
    @app.before_request
    def enforce_superadmin_2fa():
        allowed_endpoints = {
            "auth.login",
            "auth.logout",
            "auth.two_factor_setup",
            "auth.two_factor_verify",
            "static",
            "core.health",
        }

        if not current_user.is_authenticated:
            return None

        if not getattr(current_user, "is_superadmin", False):
            return None

        if session.get("2fa_verified"):
            return None

        if request.endpoint in allowed_endpoints:
            return None

        if current_user.is_2fa_enabled:
            return redirect(url_for("auth.two_factor_verify"))
        return redirect(url_for("auth.two_factor_setup"))
