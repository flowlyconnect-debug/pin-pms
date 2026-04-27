import logging

from flask import Flask
from flask import redirect, render_template, request, session, url_for
from flask_login import current_user, logout_user
from sqlalchemy.orm.exc import DetachedInstanceError, ObjectDeletedError

from app.cli import register_cli_commands
from app.config import config_by_name
from app.core.errors import copy_for as error_copy_for
from app.core.logging import configure_logging
from app.extensions import cors, csrf, db, limiter, login_manager, migrate


def create_app(config_object: str = "config.Config") -> Flask:
    app = Flask(__name__)

    selected_config = config_object or "default"
    if selected_config in config_by_name:
        app.config.from_object(config_by_name[selected_config])
    else:
        app.config.from_object(selected_config)

    if selected_config == "production" and not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set in production.")

    configure_logging(app)

    db.init_app(app)
    register_models()
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_message = "Please log in to continue."
    csrf.init_app(app)
    limiter.init_app(app)
    _init_cors(app)

    register_blueprints(app)
    register_cli_commands(app)
    register_security_guards(app)
    register_error_handlers(app)
    _maybe_start_backup_scheduler(app)

    return app


def _init_cors(app: Flask) -> None:
    """Wire up Flask-CORS for the public API only.

    Project brief section 10: "CORS sallitaan vain maaritetyille
    domaineille". The list comes from the ``CORS_ALLOWED_ORIGINS`` env
    variable (parsed in :class:`app.config.BaseConfig`); an empty list
    leaves CORS off entirely so only same-origin requests succeed.
    """
    origins = app.config.get("CORS_ALLOWED_ORIGINS") or []
    if not origins:
        return
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": origins}},
        supports_credentials=False,
        allow_headers=["Authorization", "X-API-Key", "Content-Type"],
        methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    )


def _maybe_start_backup_scheduler(app: Flask) -> None:
    """Boot the backup scheduler only for long-running web processes."""
    import sys

    if app.config.get("TESTING"):
        return

    argv = " ".join(sys.argv)
    is_cli = "flask" in argv and "flask run" not in argv
    if is_cli:
        return

    from app.backups.scheduler import init_scheduler

    init_scheduler(app)


def register_models() -> None:
    from app.api.models import ApiKey
    from app.audit.models import AuditLog
    from app.auth.models import PasswordResetToken
    from app.backups.models import Backup
    from app.billing.models import Invoice, Lease
    from app.maintenance.models import MaintenanceRequest
    from app.email.models import EmailTemplate
    from app.guests.models import Guest
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation
    from app.settings.models import Setting
    from app.users.models import User

    _ = (
        ApiKey,
        AuditLog,
        Backup,
        EmailTemplate,
        Invoice,
        Lease,
        MaintenanceRequest,
        Guest,
        Organization,
        PasswordResetToken,
        Property,
        Reservation,
        Setting,
        Unit,
        User,
    )


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
    app.register_blueprint(api_bp, url_prefix="/api/v1")
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(email_bp, url_prefix="/email")
    app.register_blueprint(backups_bp, url_prefix="/backups")

    csrf.exempt(api_bp)
    limiter.limit(app.config["API_RATE_LIMIT"])(api_bp)


def register_security_guards(app: Flask) -> None:
    @app.before_request
    def enforce_superadmin_2fa():
        allowed_endpoints = {
            "auth.login",
            "auth.logout",
            "auth.two_factor_setup",
            "auth.two_factor_verify",
            "auth.two_factor_backup_codes",
            "auth.forgot_password",
            "auth.reset_password",
            "static",
            "core.health",
        }

        try:
            is_authenticated = current_user.is_authenticated
        except (ObjectDeletedError, DetachedInstanceError):
            logout_user()
            session.pop("2fa_verified", None)
            return None

        if not is_authenticated:
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


def register_error_handlers(app: Flask) -> None:
    from werkzeug.exceptions import HTTPException

    from app.api.schemas import json_error

    logger = logging.getLogger("app.errors")

    def _render_error(code: int, description: str | None = None):
        title, default_message = error_copy_for(code)
        message = description if description else default_message
        login_link = code in (401, 403) and not current_user.is_authenticated
        return render_template(
            "error.html",
            code=code,
            title=title,
            message=message,
            login_link=login_link,
        ), code

    @app.errorhandler(HTTPException)
    def handle_http_exception(err: HTTPException):
        code = err.code or 500
        if request.path.startswith("/api/"):
            name = (err.name or "http_error").lower().replace(" ", "_")
            return json_error(
                code=name,
                message=err.description or err.name or "HTTP error",
                status=code,
            )
        description = err.description if err.description else None
        return _render_error(code, description)

    @app.errorhandler(Exception)
    def handle_unhandled_exception(err: Exception):
        if isinstance(err, HTTPException):
            return handle_http_exception(err)

        logger.exception("Unhandled exception during request")

        try:
            db.session.rollback()
        except Exception:
            logger.exception("Rollback failed after unhandled exception")

        if request.path.startswith("/api/"):
            return json_error(
                code="internal_server_error",
                message="Internal server error.",
                status=500,
            )

        return _render_error(500)
