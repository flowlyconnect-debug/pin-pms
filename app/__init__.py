import logging

from flask import Flask
from flask import redirect, render_template, request, session, url_for
from flask_login import current_user

from app.cli import register_cli_commands
from app.config import config_by_name
from app.extensions import csrf, db, limiter, login_manager, migrate


# Human-facing copy for each error code. Keep messages short and avoid
# exposing internal details; if Werkzeug gives us a more specific description
# (e.g. from a custom ``abort(403, "You are not the owner")``) we prefer it.
ERROR_COPY: dict[int, tuple[str, str]] = {
    400: ("Bad Request", "Your request could not be understood."),
    401: ("Unauthorized", "You must sign in to access this page."),
    403: ("Forbidden", "You do not have permission to access this page."),
    404: ("Not Found", "The page you requested does not exist."),
    405: ("Method Not Allowed", "This resource does not support that kind of request."),
    413: ("Payload Too Large", "The data you submitted is too large."),
    429: ("Too Many Requests", "You are making requests too quickly. Please wait and try again."),
    500: ("Internal Server Error", "Something went wrong on our side. The error has been recorded."),
}


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
    csrf.init_app(app)
    limiter.init_app(app)

    register_blueprints(app)
    register_cli_commands(app)
    register_security_guards(app)
    register_error_handlers(app)
    _maybe_start_backup_scheduler(app)

    return app


def _maybe_start_backup_scheduler(app: Flask) -> None:
    """Boot the backup scheduler only for long-running web processes.

    The scheduler must not run during ``flask db upgrade``, CLI commands like
    ``flask create-superadmin``, or pytest — the threads outlive those
    invocations and would either fire spurious dumps or block exit. We detect
    those contexts by inspecting ``sys.argv`` (CLI invocations always start
    with ``flask <command>``) and the ``TESTING`` config flag.
    """

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
    # Ensure model metadata is loaded before Flask-Migrate autogenerate.
    from app.api.models import ApiKey
    from app.audit.models import AuditLog
    from app.backups.models import Backup
    from app.email.models import EmailTemplate
    from app.organizations.models import Organization
    from app.users.models import User

    _ = (ApiKey, AuditLog, Backup, EmailTemplate, Organization, User)


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

    # The public API authenticates with long-lived, per-client API keys and
    # has no cookie-bound session to defend against. CSRF tokens would only
    # break programmatic clients (curl, SDKs, cron jobs) without adding
    # security, so the entire ``/api/v1`` surface is exempted.
    csrf.exempt(api_bp)

    # Apply the per-bucket API rate limit to every ``/api/v1/*`` route. The
    # bucket key (per-API-key when authenticated, per-IP otherwise) is
    # resolved by ``app.extensions._rate_limit_key``. Login uses a stricter,
    # endpoint-local limit applied directly on the view.
    limiter.limit(app.config["API_RATE_LIMIT"])(api_bp)


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


def register_error_handlers(app: Flask) -> None:
    """Register uniform error handlers.

    * ``/api/``        → JSON body ``{success, data, error}`` at the matching status.
    * everything else  → a branded ``error.html`` template at the matching status.
    * unhandled exceptions get logged and roll back the DB session so the
      caller does not leak an aborted transaction into the next request.
    """

    from werkzeug.exceptions import HTTPException

    from app.api.schemas import json_error

    logger = logging.getLogger("app.errors")

    def _render_error(code: int, description: str | None = None):
        """Return an HTML response for the given status code."""

        title, default_message = ERROR_COPY.get(
            code, ("HTTP Error", "An unexpected error occurred.")
        )
        # Respect custom messages passed into abort(code, "...").
        message = description if description else default_message
        # Show a login link for auth-related codes.
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
        # Werkzeug's default description is sometimes helpful (e.g. "The method
        # is not allowed for the requested URL."). Fall back to our copy if the
        # description is generic or missing.
        description = err.description if err.description else None
        return _render_error(code, description)

    @app.errorhandler(Exception)
    def handle_unhandled_exception(err: Exception):
        # Flask chooses the most specific handler first, so HTTPExceptions
        # are already routed to ``handle_http_exception``. This handler only
        # fires for genuine bugs — but we defensively delegate just in case.
        if isinstance(err, HTTPException):
            return handle_http_exception(err)

        logger.exception("Unhandled exception during request")

        # Roll back any pending DB changes so the next request starts clean.
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001 — rollback must never raise further.
            logger.exception("Rollback failed after unhandled exception")

        if request.path.startswith("/api/"):
            return json_error(
                code="internal_server_error",
                message="Internal server error.",
                status=500,
            )

        return _render_error(500)
