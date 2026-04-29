from __future__ import annotations

from datetime import date
from functools import wraps

from flask import abort, current_app, flash, redirect, render_template, request, session, url_for

from app.audit import record as audit_record
from app.audit.models import ActorType, AuditStatus
from app.email.models import TemplateKey
from app.email.services import EmailTemplateNotFound, send_template
from app.extensions import limiter
from app.portal import portal_bp
from app.portal import services as portal_service


def _login_rate_limit():
    return current_app.config["LOGIN_RATE_LIMIT"]


def _current_portal_user():
    user_id = session.get("portal_user_id")
    return portal_service.get_portal_user_or_none(user_id=user_id)


def require_portal_login(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        user = _current_portal_user()
        if user is None:
            return redirect(url_for("portal.login"))
        return view_func(user, *args, **kwargs)

    return wrapped


@portal_bp.route("/login", methods=["GET", "POST"])
@limiter.limit(
    _login_rate_limit,
    methods=["POST"],
    error_message="Too many login attempts. Please wait and try again.",
)
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = portal_service.authenticate_portal_user(email=email, password=password)
        if user is None:
            audit_record(
                "portal.login.failure",
                status=AuditStatus.FAILURE,
                actor_type=ActorType.ANONYMOUS,
                actor_email=email or None,
                commit=True,
            )
            return render_template("portal/login.html", error="Invalid email or password.")
        session["portal_user_id"] = user.id
        audit_record(
            "portal.login.success",
            status=AuditStatus.SUCCESS,
            actor_type=ActorType.USER,
            actor_id=user.id,
            actor_email=user.email,
            organization_id=user.organization_id,
            target_type="user",
            target_id=user.id,
            commit=True,
        )
        return redirect(url_for("portal.dashboard"))
    return render_template("portal/login.html", error=None)


@portal_bp.route("/magic-link", methods=["POST"])
@limiter.limit(
    _login_rate_limit,
    methods=["POST"],
    error_message="Too many attempts. Please wait and try again.",
)
def request_magic_link():
    email = (request.form.get("email") or "").strip().lower()
    issued = portal_service.issue_magic_link(email=email)
    if issued is not None:
        row, raw_token = issued
        magic_url = url_for("portal.magic_link_login", token=raw_token, _external=True)
        try:
            send_template(
                TemplateKey.ADMIN_NOTIFICATION,
                to=email,
                context={
                    "user_email": email,
                    "subject_line": "Your Pindora portal magic link",
                    "message": f"Use this link to sign in: {magic_url}",
                },
            )
        except EmailTemplateNotFound:
            current_app.logger.warning("Magic link email template missing for portal login.")
        except Exception:  # noqa: BLE001
            current_app.logger.exception("Failed sending portal magic link email.")
        audit_record(
            "portal.magic_link.issued",
            status=AuditStatus.SUCCESS,
            actor_type=ActorType.USER,
            actor_id=row.user_id,
            actor_email=email,
            target_type="user",
            target_id=row.user_id,
            commit=True,
        )
    flash("If your account exists, a magic link has been sent.")
    return redirect(url_for("portal.login"))


@portal_bp.get("/magic/<token>")
def magic_link_login(token: str):
    user = portal_service.authenticate_by_magic_link(raw_token=token)
    if user is None:
        abort(404)
    session["portal_user_id"] = user.id
    audit_record(
        "portal.magic_link.login",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=user.id,
        actor_email=user.email,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user.id,
        commit=True,
    )
    return redirect(url_for("portal.dashboard"))


@portal_bp.get("/logout")
def logout():
    session.pop("portal_user_id", None)
    flash("Logged out.")
    return redirect(url_for("portal.login"))


@portal_bp.get("/dashboard")
@require_portal_login
def dashboard(user):
    stats = portal_service.get_dashboard_stats(
        organization_id=user.organization_id,
        guest_id=user.id,
    )
    return render_template("portal/dashboard.html", stats=stats)


@portal_bp.get("/reservations")
@require_portal_login
def reservations(user):
    rows = portal_service.list_reservations(
        organization_id=user.organization_id,
        guest_id=user.id,
    )
    return render_template("portal/reservations.html", rows=rows)


@portal_bp.get("/reservations/<int:reservation_id>")
@require_portal_login
def reservation_detail(user, reservation_id: int):
    try:
        row = portal_service.get_reservation(
            organization_id=user.organization_id,
            guest_id=user.id,
            reservation_id=reservation_id,
        )
    except portal_service.PortalServiceError:
        abort(404)
    return render_template("portal/reservation_detail.html", row=row)


@portal_bp.get("/invoices")
@require_portal_login
def invoices(user):
    rows = portal_service.list_invoices(
        organization_id=user.organization_id,
        guest_id=user.id,
    )
    return render_template("portal/invoices.html", rows=rows)


@portal_bp.route("/maintenance", methods=["GET", "POST"])
@require_portal_login
def maintenance(user):
    error = None
    if request.method == "POST":
        reservation_id_raw = (request.form.get("reservation_id") or "").strip()
        try:
            reservation_id = int(reservation_id_raw)
            _ = portal_service.create_maintenance_request(
                organization_id=user.organization_id,
                guest_id=user.id,
                reservation_id=reservation_id,
                title=(request.form.get("title") or "").strip(),
                description=(request.form.get("description") or "").strip() or None,
                priority=(request.form.get("priority") or "normal").strip().lower(),
                due_date_raw=(request.form.get("due_date") or "").strip() or None,
            )
        except ValueError:
            error = "Reservation is required."
        except portal_service.PortalServiceError as exc:
            if exc.status == 404:
                abort(404)
            error = exc.message
        else:
            flash("Maintenance request created.")
            return redirect(url_for("portal.maintenance"))
    rows = portal_service.list_maintenance_requests(
        organization_id=user.organization_id,
        guest_id=user.id,
    )
    options = portal_service.maintenance_form_scope(
        organization_id=user.organization_id,
        guest_id=user.id,
    )
    return render_template("portal/maintenance.html", rows=rows, options=options, error=error)


@portal_bp.get("/maintenance/<int:request_id>")
@require_portal_login
def maintenance_detail(user, request_id: int):
    try:
        row = portal_service.get_maintenance_request(
            organization_id=user.organization_id,
            guest_id=user.id,
            request_id=request_id,
        )
    except portal_service.PortalServiceError:
        abort(404)
    return render_template("portal/maintenance_detail.html", row=row)


@portal_bp.route("/check-in/<token>", methods=["GET", "POST"])
def check_in(token: str):
    if request.method == "GET":
        return render_template("portal/checkin.html", error=None, access_code=None)
    full_name = (request.form.get("full_name") or "").strip()
    dob_raw = (request.form.get("date_of_birth") or "").strip()
    rules_signature = (request.form.get("rules_signature") or "").strip()
    idempotency_key = (
        (request.headers.get("Idempotency-Key") or "").strip()
        or (request.form.get("idempotency_key") or "").strip()
        or None
    )
    file = request.files.get("id_document")
    if not full_name or not dob_raw or not rules_signature or file is None or not file.filename:
        return (
            render_template(
                "portal/checkin.html",
                error="All fields are required for online check-in.",
                access_code=None,
            ),
            400,
        )
    try:
        dob = date.fromisoformat(dob_raw)
    except ValueError:
        return (
            render_template("portal/checkin.html", error="Invalid birth date.", access_code=None),
            400,
        )
    try:
        _, access_code = portal_service.complete_checkin(
            token=token,
            full_name=full_name,
            date_of_birth=dob,
            id_document_bytes=file.read(),
            id_document_name=file.filename,
            rules_signature=rules_signature,
            idempotency_key=idempotency_key,
        )
    except portal_service.PortalServiceError as exc:
        if exc.status == 404:
            abort(404)
        return (
            render_template("portal/checkin.html", error=exc.message, access_code=None),
            exc.status,
        )
    return render_template("portal/checkin.html", error=None, access_code=access_code)
