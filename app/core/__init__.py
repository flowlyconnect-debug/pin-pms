from flask import Blueprint, current_app, render_template
from flask_login import current_user
from sqlalchemy import inspect, text

from app.extensions import db

core_bp = Blueprint("core", __name__)


@core_bp.get("/")
def index():
    return render_template("index.html", current_user=current_user)


@core_bp.get("/health")
def health():
    return {"status": "ok"}, 200


@core_bp.get("/health/db")
def health_db():
    """DB-skeema-diagnoosi.

    Palauttaa migraation tilan ja ne kolme uutta saraketta/taulua, joiden
    pitäisi olla olemassa kun ``flask db upgrade`` on ajettu uusimpaan
    versioon. Auttaa selvittämään miksi /login kaatuu.

    Disabled tuotannossa (DEBUG=0).
    """

    if not current_app.debug:
        return {"error": "disabled in production"}, 403

    inspector = inspect(db.engine)

    def column_names(table):
        try:
            return {col["name"] for col in inspector.get_columns(table)}
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {type(exc).__name__}: {exc}"

    def has_table(table):
        try:
            return inspector.has_table(table)
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {type(exc).__name__}: {exc}"

    try:
        version = db.session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    except Exception as exc:  # noqa: BLE001
        version = f"ERROR: {type(exc).__name__}: {exc}"

    expected_users_columns = column_names("users")
    expected_backups_columns = column_names("backups")

    return {
        "alembic_version": version,
        "tables": {
            "users_exists": has_table("users"),
            "backups_exists": has_table("backups"),
            "password_reset_tokens_exists": has_table("password_reset_tokens"),
            "leases_exists": has_table("leases"),
            "invoices_exists": has_table("invoices"),
            "maintenance_requests_exists": has_table("maintenance_requests"),
            "portal_magic_link_tokens_exists": has_table("portal_magic_link_tokens"),
        },
        "users_columns": (
            sorted(expected_users_columns)
            if isinstance(expected_users_columns, set)
            else expected_users_columns
        ),
        "users_has_backup_codes": (
            "backup_codes" in expected_users_columns
            if isinstance(expected_users_columns, set)
            else False
        ),
        "backups_has_uploads_filename": (
            "uploads_filename" in expected_backups_columns
            if isinstance(expected_backups_columns, set)
            else False
        ),
        "backups_has_s3_uri": (
            "s3_uri" in expected_backups_columns
            if isinstance(expected_backups_columns, set)
            else False
        ),
    }, 200
