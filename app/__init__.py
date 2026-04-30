import logging
import time
import uuid

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from flask import Flask, g, redirect, render_template, request, session, url_for
from flask_login import current_user, logout_user
from sqlalchemy import event
from sqlalchemy.orm.exc import DetachedInstanceError, ObjectDeletedError

from app.cli import register_cli_commands
from app.config import config_by_name
from app.core.errors import copy_for as error_copy_for
from app.core.logging import configure_logging
from app.core.security_headers import register_security_headers
from app.core.telemetry import init_tracing
from app.extensions import cors, csrf, db, limiter, login_manager, migrate


def create_app(config_object: str = "default") -> Flask:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    app = Flask(__name__)

    selected_config = config_object or "default"
    if selected_config in config_by_name:
        app.config.from_object(config_by_name[selected_config])
    else:
        app.config.from_object(selected_config)

    if not app.config.get("TESTING"):
        from app.config import _resolved_database_url

        app.config["SQLALCHEMY_DATABASE_URI"] = _resolved_database_url()

    if selected_config == "production" and not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set in production.")

    _init_sentry(app)
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
    register_request_context_hooks(app)
    register_security_headers(app)
    register_slow_query_logging(app)
    register_error_handlers(app)
    _maybe_start_backup_scheduler(app)
    _maybe_start_email_scheduler(app)
    _maybe_start_portal_scheduler(app)
    _maybe_start_ical_scheduler(app)
    _maybe_start_api_scheduler(app)
    _maybe_start_owner_scheduler(app)
    _maybe_start_status_scheduler(app)
    init_tracing(app)

    return app


def _init_sentry(app: Flask) -> None:
    dsn = (app.config.get("SENTRY_DSN") or "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
    except Exception:
        app.logger.warning("Sentry SDK not available; skipping Sentry init")
        return
    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        traces_sample_rate=float(app.config.get("SENTRY_TRACES_SAMPLE_RATE", 0.1)),
    )


def _init_cors(app):
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


def _scheduler_should_skip(app):
    import sys

    if app.config.get("TESTING"):
        return True
    argv = " ".join(sys.argv)
    return "flask" in argv and "flask run" not in argv


def _maybe_start_backup_scheduler(app):
    if _scheduler_should_skip(app):
        return
    from app.backups.scheduler import init_scheduler

    scheduler = init_scheduler(app)
    _register_scheduler(app, "backups", scheduler)


def _maybe_start_portal_scheduler(app):
    if _scheduler_should_skip(app):
        return
    from app.portal.scheduler import init_scheduler

    scheduler = init_scheduler(app)
    _register_scheduler(app, "portal", scheduler)


def _maybe_start_email_scheduler(app):
    if _scheduler_should_skip(app):
        return
    from app.email.scheduler import init_scheduler

    scheduler = init_scheduler(app)
    _register_scheduler(app, "email", scheduler)


def _maybe_start_ical_scheduler(app):
    if _scheduler_should_skip(app):
        return
    from app.integrations.ical.scheduler import init_scheduler

    scheduler = init_scheduler(app)
    _register_scheduler(app, "ical", scheduler)


def _maybe_start_api_scheduler(app):
    if _scheduler_should_skip(app):
        return
    from app.api.scheduler import init_scheduler

    scheduler = init_scheduler(app)
    _register_scheduler(app, "api", scheduler)


def _maybe_start_owner_scheduler(app):
    if _scheduler_should_skip(app):
        return
    from app.owners.scheduler import init_scheduler

    scheduler = init_scheduler(app)
    _register_scheduler(app, "owners", scheduler)


def _maybe_start_status_scheduler(app):
    if _scheduler_should_skip(app):
        return
    from app.status.scheduler import init_scheduler

    scheduler = init_scheduler(app)
    _register_scheduler(app, "status", scheduler)


def _register_scheduler(app, name: str, scheduler) -> None:
    if not hasattr(app, "extensions"):
        return
    registry = app.extensions.setdefault("apscheduler_instances", {})
    registry[name] = scheduler


def register_request_context_hooks(app):
    @app.before_request
    def assign_request_id():
        g.request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())

    @app.after_request
    def include_request_id_header(response):
        response.headers["X-Request-Id"] = getattr(g, "request_id", "")
        return response


def register_slow_query_logging(app):
    threshold_ms = int(app.config.get("SQL_SLOW_QUERY_MS", 500))
    with app.app_context():
        engine = db.engine

        @event.listens_for(engine, "before_cursor_execute")
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            _ = (conn, cursor, statement, parameters, executemany)
            context._query_started_at = time.perf_counter()

        @event.listens_for(engine, "after_cursor_execute")
        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            _ = (conn, cursor, executemany)
            started = getattr(context, "_query_started_at", None)
            if started is None:
                return
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if elapsed_ms < threshold_ms:
                return
            app.logger.warning(
                "slow_query_detected",
                extra={
                    "query_ms": elapsed_ms,
                    "sql": statement[:500],
                    "sql_parameters": str(parameters)[:300],
                },
            )


def register_models():
    from app.api.models import ApiKey, ApiKeyUsage
    from app.audit.models import AuditLog
    from app.auth.models import PasswordResetToken, TwoFactorEmailCode
    from app.backups.models import Backup
    from app.email.models import EmailTemplate, OutgoingEmail
    from app.guests.models import Guest
    from app.organizations.models import Organization
    from app.owners.models import OwnerPayout, OwnerUser, PropertyOwner, PropertyOwnerAssignment
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation
    from app.settings.models import Setting
    from app.subscriptions.models import SubscriptionPlan
    from app.users.models import User

    try:
        from app.billing.models import Invoice, Lease  # noqa: F401
    except Exception:
        pass
    try:
        from app.maintenance.models import MaintenanceRequest  # noqa: F401
    except Exception:
        pass
    try:
        from app.portal.models import (  # noqa: F401
            AccessCode,
            GuestCheckIn,
            LockDevice,
            PortalCheckInToken,
            PortalMagicLinkToken,
        )
    except Exception:
        pass
    try:
        from app.integrations.ical.models import (  # noqa: F401
            ImportedCalendarEvent,
            ImportedCalendarFeed,
        )
    except Exception:
        pass
    try:
        from app.status.models import StatusCheck, StatusComponent, StatusIncident  # noqa: F401
    except Exception:
        pass

    _ = (
        ApiKey,
        ApiKeyUsage,
        AuditLog,
        Backup,
        EmailTemplate,
        Guest,
        Organization,
        PasswordResetToken,
        Property,
        Reservation,
        Setting,
        SubscriptionPlan,
        TwoFactorEmailCode,
        Unit,
        User,
    )
    _ = OutgoingEmail
    _ = (OwnerPayout, OwnerUser, PropertyOwner, PropertyOwnerAssignment)


@login_manager.user_loader
def load_user(user_id):
    from app.users.models import User

    return User.query.get(int(user_id))


def register_blueprints(app):
    from app.admin import admin_bp
    from app.api import api_bp
    from app.api.rate_limits import resolve_api_rate_limit
    from app.auth import auth_bp
    from app.backups import backups_admin_bp, backups_bp
    from app.core import core_bp
    from app.email import email_bp
    from app.users import users_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(backups_admin_bp, url_prefix="/admin/backups")
    app.register_blueprint(api_bp, url_prefix="/api/v1")
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(email_bp, url_prefix="/email")
    app.register_blueprint(backups_bp, url_prefix="/backups")

    try:
        from app.portal import portal_bp

        app.register_blueprint(portal_bp, url_prefix="/portal")
    except Exception as exc:
        app.logger.warning("portal blueprint not registered: %s", exc)
    try:
        from app.owner_portal import owner_portal_bp

        app.register_blueprint(owner_portal_bp, url_prefix="/owner")
    except Exception as exc:
        app.logger.warning("owner portal blueprint not registered: %s", exc)

    csrf.exempt(api_bp)
    limiter.limit(resolve_api_rate_limit)(api_bp)


def register_security_guards(app):
    @app.before_request
    def enforce_superadmin_2fa():
        allowed_endpoints = {
            "auth.login",
            "auth.logout",
            "auth.two_factor_setup",
            "auth.two_factor_verify",
            "auth.two_factor_email_code",
            "auth.two_factor_backup_codes",
            "auth.forgot_password",
            "auth.reset_password",
            "static",
            "core.health",
            "core.health_db",
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

    @app.context_processor
    def inject_impersonation_state():
        return {"impersonation_active": bool(session.get("impersonator_user_id"))}


def register_error_handlers(app):
    from werkzeug.exceptions import HTTPException

    from app.api.schemas import json_error

    logger = logging.getLogger("app.errors")

    def _render_error(code, description=None):
        title, default_message = error_copy_for(code)
        message = description if description else default_message
        login_link = code in (401, 403) and not current_user.is_authenticated
        return (
            render_template(
                "error.html",
                code=code,
                title=title,
                message=message,
                login_link=login_link,
            ),
            code,
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
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
    def handle_unhandled_exception(err):
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
