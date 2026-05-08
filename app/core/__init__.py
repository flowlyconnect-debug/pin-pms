from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import inspect, text

from app.extensions import db
from app.integrations.ical.service import IcalService

core_bp = Blueprint("core", __name__)


@core_bp.get("/")
def index():
    """Route root users directly to their real destination.

    Root must never render the legacy fallback landing HTML, because that can
    flash briefly before the actual login page is displayed. We always issue
    a server-side redirect instead.
    """

    if current_user.is_authenticated:
        role = getattr(current_user, "role", None)
        role_value = getattr(role, "value", role)
        if role_value in ("admin", "superadmin"):
            return redirect(url_for("admin.admin_home"))
        return redirect(url_for("portal.dashboard"))

    return redirect(url_for("auth.login"))


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
        version = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()
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


@core_bp.get("/status")
def public_status():
    from app.admin import services as admin_service

    payload = admin_service.public_status_payload(window_days=90)
    has_open_incident = any(i.status != "resolved" for i in payload["incidents"])
    return render_template("status.html", payload=payload, has_open_incident=has_open_incident)


@core_bp.get("/accessibility")
def accessibility_statement():
    return render_template("accessibility.html")


@core_bp.get("/accessibility-statement")
def accessibility_statement_legacy():
    return redirect(url_for("core.accessibility_statement"))


@core_bp.get("/lease/sign/<signed_token>")
def lease_sign_get(signed_token: str):
    from app.billing import services as billing_service

    try:
        row = billing_service.get_lease_by_signed_token(signed_token=signed_token)
    except billing_service.LeaseServiceError:
        return (
            render_template(
                "lease/sign.html", error="Allekirjoituslinkki ei ole kelvollinen.", row=None
            ),
            404,
        )
    return render_template("lease/sign.html", row=row, token=signed_token, error=None)


@core_bp.post("/lease/sign/<signed_token>")
def lease_sign_post(signed_token: str):
    from app.billing import services as billing_service

    try:
        row = billing_service.sign_lease_with_token(
            signed_token=signed_token,
            signed_ip=request.headers.get("X-Forwarded-For", request.remote_addr),
            signed_user_agent=request.headers.get("User-Agent"),
        )
    except billing_service.LeaseServiceError:
        return (
            render_template(
                "lease/sign.html", error="Allekirjoituslinkki ei ole kelvollinen.", row=None
            ),
            404,
        )
    return render_template("lease/sign.html", row=row, token=signed_token, signed=True, error=None)


@core_bp.get("/api/conflicts")
def conflicts_api():
    if not current_user.is_authenticated:
        abort(401)
    role = getattr(current_user, "role", None)
    role_value = getattr(role, "value", role)
    if role_value not in ("admin", "superadmin"):
        abort(403)

    organization_id = current_user.organization_id
    if role_value == "superadmin":
        requested_org = (request.args.get("organization_id") or "").strip()
        if requested_org.isdigit():
            organization_id = int(requested_org)

    rows = IcalService().detect_conflicts(organization_id=organization_id)
    items = [
        {
            "reservation_id": row.get("reservation_id"),
            "unit_id": row.get("unit_id"),
            "reservation_start": str(row.get("reservation_start") or ""),
            "reservation_end": str(row.get("reservation_end") or ""),
            "external_start": str(row.get("external_start") or ""),
            "external_end": str(row.get("external_end") or ""),
            "external_summary": row.get("external_summary"),
        }
        for row in rows
    ]
    return {"count": len(items), "items": items}, 200
