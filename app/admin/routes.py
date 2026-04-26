"""Admin-only views — audit log browser and email-template editor.

All routes in this blueprint require an authenticated superadmin whose TOTP
2FA session is verified. Reuses the decorator declared in :mod:`app.auth.routes`
so the 2FA gate stays in a single place.
"""
from __future__ import annotations

from functools import wraps

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.admin import admin_bp
from app.admin import services as admin_service
from app.audit import record as audit_record
from app.audit.models import AuditLog, AuditStatus
from app.auth.routes import require_superadmin_2fa
from app.backups.models import Backup, BackupTrigger
from app.backups.services import BackupError, create_backup, restore_backup
from app.email.models import EmailTemplate
from app.email.services import render_strings as render_email_strings
from app.extensions import db
from app.settings import services as settings_service
from app.settings.models import Setting, SettingType
from app.properties import services as property_service
from app.properties.models import Property, Unit
from app.reports import services as report_service
from app.reservations import services as reservation_service
from app.users.models import User, UserRole


PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 200


def _is_admin_or_superadmin() -> bool:
    return current_user.role in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}


def require_admin_pms_access(view_func):
    @wraps(view_func)
    @login_required
    def wrapped(*args, **kwargs):
        if not _is_admin_or_superadmin():
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped


def _pms_org_id() -> int:
    # TODO: If a safe, explicit superadmin cross-tenant override is introduced
    # in the future, centralize it here. For now we keep strict tenant scope.
    return current_user.organization_id


def _pms_pagination() -> tuple[int, int]:
    try:
        page = max(int(request.args.get("page", "1")), 1)
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get("per_page", "25"))
    except ValueError:
        per_page = 25
    per_page = max(1, min(per_page, 100))
    return page, per_page


@admin_bp.get("")
@admin_bp.get("/")
@admin_bp.get("/dashboard")
@require_admin_pms_access
def admin_home():
    summary = admin_service.get_dashboard_stats(organization_id=_pms_org_id())
    return render_template("admin/dashboard.html", summary=summary)


@admin_bp.get("/calendar")
@require_admin_pms_access
def calendar_page():
    return render_template("admin/calendar.html")


@admin_bp.get("/calendar/events")
@require_admin_pms_access
def calendar_events():
    try:
        start_d = reservation_service.parse_calendar_iso_bound(request.args.get("start"))
        end_d = reservation_service.parse_calendar_iso_bound(request.args.get("end"))
    except ValueError:
        abort(400)
    events = reservation_service.get_calendar_events(
        organization_id=_pms_org_id(),
        start_date=start_d,
        end_date=end_d,
    )
    return jsonify(events)


def _reservation_form_choices(*, organization_id: int) -> tuple[list[Unit], list[User]]:
    units = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
        .order_by(Property.id.asc(), Unit.id.asc())
        .all()
    )
    users = (
        User.query.filter_by(organization_id=organization_id)
        .order_by(User.id.asc())
        .all()
    )
    return units, users


def _reservation_edit_return_target(raw: str | None) -> str:
    """Where to redirect after a successful reservation edit (allowlist)."""

    value = (raw or "").strip().lower()
    if value in {"calendar", "detail", "list"}:
        return value
    return "calendar"


def _reservation_edit_form_context(*, organization_id: int) -> tuple[list[Property], list[Unit]]:
    properties = (
        Property.query.filter_by(organization_id=organization_id)
        .order_by(Property.name.asc(), Property.id.asc())
        .all()
    )
    units = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
        .order_by(Property.name.asc(), Unit.name.asc(), Unit.id.asc())
        .all()
    )
    return properties, units


@admin_bp.get("/properties")
@require_admin_pms_access
def properties_list():
    page, per_page = _pms_pagination()
    rows, total = property_service.list_properties_paginated(
        organization_id=_pms_org_id(),
        page=page,
        per_page=per_page,
    )
    return render_template(
        "admin/properties/list.html",
        rows=rows,
        page=page,
        per_page=per_page,
        total=total,
    )


@admin_bp.route("/properties/new", methods=["GET", "POST"])
@require_admin_pms_access
def properties_new():
    form = {"name": "", "address": ""}
    error: str | None = None

    if request.method == "POST":
        form["name"] = (request.form.get("name") or "").strip()
        form["address"] = (request.form.get("address") or "").strip()
        try:
            row = property_service.create_property(
                organization_id=_pms_org_id(),
                name=form["name"],
                address=form["address"],
                actor_user_id=current_user.id,
            )
        except property_service.PropertyServiceError as err:
            error = err.message
        else:
            flash("Property created.")
            return redirect(url_for("admin.properties_detail", property_id=row["id"]))

    return render_template("admin/properties/new.html", form=form, error=error)


@admin_bp.get("/properties/<int:property_id>")
@require_admin_pms_access
def properties_detail(property_id: int):
    try:
        row = property_service.get_property(
            organization_id=_pms_org_id(),
            property_id=property_id,
        )
    except property_service.PropertyServiceError:
        abort(404)
    return render_template("admin/properties/detail.html", row=row)


@admin_bp.route("/properties/<int:property_id>/edit", methods=["GET", "POST"])
@require_admin_pms_access
def properties_edit(property_id: int):
    try:
        row = property_service.get_property(
            organization_id=_pms_org_id(),
            property_id=property_id,
        )
    except property_service.PropertyServiceError:
        abort(404)

    form = {
        "name": row["name"],
        "address": row["address"] or "",
    }
    error: str | None = None

    if request.method == "POST":
        form["name"] = (request.form.get("name") or "").strip()
        form["address"] = (request.form.get("address") or "").strip()
        try:
            row = property_service.update_property(
                organization_id=_pms_org_id(),
                property_id=property_id,
                name=form["name"],
                address=form["address"],
                actor_user_id=current_user.id,
            )
        except property_service.PropertyServiceError as err:
            error = err.message
        else:
            flash("Property updated.")
            return redirect(url_for("admin.properties_detail", property_id=row["id"]))

    return render_template("admin/properties/edit.html", row=row, form=form, error=error)


@admin_bp.get("/properties/<int:property_id>/units")
@require_admin_pms_access
def units_list(property_id: int):
    try:
        property_row = property_service.get_property(
            organization_id=_pms_org_id(),
            property_id=property_id,
        )
        rows = property_service.list_units(
            organization_id=_pms_org_id(),
            property_id=property_id,
        )
    except property_service.PropertyServiceError:
        abort(404)
    return render_template("admin/units/list.html", property_row=property_row, rows=rows)


@admin_bp.route("/properties/<int:property_id>/units/new", methods=["GET", "POST"])
@require_admin_pms_access
def units_new(property_id: int):
    try:
        property_row = property_service.get_property(
            organization_id=_pms_org_id(),
            property_id=property_id,
        )
    except property_service.PropertyServiceError:
        abort(404)

    form = {"name": "", "unit_type": ""}
    error: str | None = None

    if request.method == "POST":
        form["name"] = (request.form.get("name") or "").strip()
        form["unit_type"] = (request.form.get("unit_type") or "").strip()
        try:
            _ = property_service.create_unit(
                organization_id=_pms_org_id(),
                property_id=property_id,
                name=form["name"],
                unit_type=form["unit_type"],
                actor_user_id=current_user.id,
            )
        except property_service.PropertyServiceError as err:
            error = err.message
        else:
            flash("Unit created.")
            return redirect(url_for("admin.units_list", property_id=property_id))

    return render_template(
        "admin/units/new.html",
        property_row=property_row,
        form=form,
        error=error,
    )


@admin_bp.route("/units/<int:unit_id>/edit", methods=["GET", "POST"])
@require_admin_pms_access
def units_edit(unit_id: int):
    try:
        row = property_service.get_unit(
            organization_id=_pms_org_id(),
            unit_id=unit_id,
        )
    except property_service.PropertyServiceError:
        abort(404)

    form = {
        "name": row["name"],
        "unit_type": row["unit_type"] or "",
    }
    error: str | None = None

    if request.method == "POST":
        form["name"] = (request.form.get("name") or "").strip()
        form["unit_type"] = (request.form.get("unit_type") or "").strip()
        try:
            row = property_service.update_unit(
                organization_id=_pms_org_id(),
                unit_id=unit_id,
                name=form["name"],
                unit_type=form["unit_type"],
                actor_user_id=current_user.id,
            )
        except property_service.PropertyServiceError as err:
            error = err.message
        else:
            flash("Unit updated.")
            return redirect(url_for("admin.units_list", property_id=row["property_id"]))

    return render_template("admin/units/edit.html", row=row, form=form, error=error)


@admin_bp.get("/reservations")
@require_admin_pms_access
def reservations_list():
    page, per_page = _pms_pagination()
    rows, total = reservation_service.list_reservations_paginated(
        organization_id=_pms_org_id(),
        page=page,
        per_page=per_page,
    )
    return render_template(
        "admin/reservations/list.html",
        rows=rows,
        page=page,
        per_page=per_page,
        total=total,
    )


@admin_bp.route("/reservations/new", methods=["GET", "POST"])
@require_admin_pms_access
def reservations_new():
    units, users = _reservation_form_choices(organization_id=_pms_org_id())
    form = {
        "unit_id": "",
        "guest_id": "",
        "start_date": "",
        "end_date": "",
    }
    error: str | None = None

    if request.method == "POST":
        form["unit_id"] = (request.form.get("unit_id") or "").strip()
        form["guest_id"] = (request.form.get("guest_id") or "").strip()
        form["start_date"] = (request.form.get("start_date") or "").strip()
        form["end_date"] = (request.form.get("end_date") or "").strip()

        if not form["unit_id"] or not form["guest_id"] or not form["start_date"] or not form["end_date"]:
            error = "All fields are required."
        else:
            try:
                row = reservation_service.create_reservation(
                    organization_id=_pms_org_id(),
                    unit_id=int(form["unit_id"]),
                    guest_id=int(form["guest_id"]),
                    start_date_raw=form["start_date"],
                    end_date_raw=form["end_date"],
                    actor_user_id=current_user.id,
                )
            except (TypeError, ValueError):
                error = "Unit and guest must be valid numeric IDs."
            except reservation_service.ReservationServiceError as err:
                error = err.message
            else:
                flash("Reservation created.")
                return redirect(url_for("admin.reservations_detail", reservation_id=row["id"]))

    return render_template(
        "admin/reservations/new.html",
        units=units,
        users=users,
        form=form,
        error=error,
    )


@admin_bp.get("/reservations/<int:reservation_id>")
@require_admin_pms_access
def reservations_detail(reservation_id: int):
    try:
        row = reservation_service.get_reservation(
            organization_id=_pms_org_id(),
            reservation_id=reservation_id,
        )
    except reservation_service.ReservationServiceError:
        abort(404)
    return render_template("admin/reservations/detail.html", row=row)


@admin_bp.route("/reservations/<int:reservation_id>/edit", methods=["GET", "POST"])
@require_admin_pms_access
def reservations_edit(reservation_id: int):
    org_id = _pms_org_id()
    properties, units = _reservation_edit_form_context(organization_id=org_id)
    return_to = _reservation_edit_return_target(request.args.get("next"))

    if request.method == "POST":
        return_to = _reservation_edit_return_target(request.form.get("return_to"))

    try:
        row = reservation_service.get_reservation_for_edit(
            organization_id=org_id,
            reservation_id=reservation_id,
        )
    except reservation_service.ReservationServiceError:
        abort(404)

    form = {
        "guest_name": row["guest_name"],
        "property_id": str(row["property_id"] or ""),
        "unit_id": str(row["unit_id"]),
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "status": row["status"],
        "return_to": return_to,
    }
    error: str | None = None

    if request.method == "POST":
        form["guest_name"] = (request.form.get("guest_name") or "").strip()
        form["property_id"] = (request.form.get("property_id") or "").strip()
        form["unit_id"] = (request.form.get("unit_id") or "").strip()
        form["start_date"] = (request.form.get("start_date") or "").strip()
        form["end_date"] = (request.form.get("end_date") or "").strip()
        form["status"] = (request.form.get("status") or "").strip()
        form["return_to"] = return_to

        payload = {
            "guest_name": form["guest_name"],
            "property_id": form["property_id"],
            "unit_id": form["unit_id"],
            "start_date": form["start_date"],
            "end_date": form["end_date"],
            "status": form["status"],
        }
        try:
            _ = reservation_service.update_reservation(
                reservation_id=reservation_id,
                organization_id=org_id,
                data=payload,
                actor_user_id=current_user.id,
            )
        except reservation_service.ReservationServiceError as err:
            if err.status == 404:
                abort(404)
            error = err.message
        else:
            flash("Reservation updated.")
            if return_to == "calendar":
                return redirect(url_for("admin.calendar_page"))
            if return_to == "list":
                return redirect(url_for("admin.reservations_list"))
            return redirect(url_for("admin.reservations_detail", reservation_id=reservation_id))

    return render_template(
        "admin/reservations/edit.html",
        row=row,
        form=form,
        properties=properties,
        units=units,
        error=error,
    )


@admin_bp.post("/reservations/<int:reservation_id>/cancel")
@require_admin_pms_access
def reservations_cancel(reservation_id: int):
    if (request.form.get("confirm_cancel") or "").strip().lower() != "yes":
        flash("Please confirm cancellation.")
        return redirect(url_for("admin.reservations_detail", reservation_id=reservation_id))

    try:
        _ = reservation_service.cancel_reservation(
            organization_id=_pms_org_id(),
            reservation_id=reservation_id,
            actor_user_id=current_user.id,
        )
    except reservation_service.ReservationServiceError:
        abort(404)

    flash("Reservation cancelled.")
    return redirect(url_for("admin.reservations_detail", reservation_id=reservation_id))


@admin_bp.get("/reports")
@require_admin_pms_access
def reports_index():
    return render_template("admin/reports/index.html")


@admin_bp.get("/reports/occupancy")
@require_admin_pms_access
def reports_occupancy():
    data = None
    error: str | None = None
    start_date_raw = (request.args.get("start_date") or "").strip()
    end_date_raw = (request.args.get("end_date") or "").strip()

    if start_date_raw or end_date_raw:
        if not start_date_raw or not end_date_raw:
            error = "Both start date and end date are required."
        else:
            from datetime import date

            try:
                start_date = date.fromisoformat(start_date_raw)
                end_date = date.fromisoformat(end_date_raw)
            except ValueError:
                error = "Dates must be valid ISO dates (YYYY-MM-DD)."
            else:
                if start_date >= end_date:
                    error = "Start date must be before end date."
                else:
                    data = report_service.occupancy_report(
                        organization_id=_pms_org_id(),
                        start_date=start_date,
                        end_date=end_date,
                    )

    return render_template(
        "admin/reports/occupancy.html",
        data=data,
        error=error,
        start_date=start_date_raw,
        end_date=end_date_raw,
    )


@admin_bp.get("/reports/reservations")
@require_admin_pms_access
def reports_reservations():
    data = report_service.reservation_report(organization_id=_pms_org_id())
    return render_template("admin/reports/reservations.html", data=data)


@admin_bp.get("/audit")
@require_superadmin_2fa
def audit():
    """List audit events, newest first, with basic filtering and pagination."""

    try:
        page = max(int(request.args.get("page", "1")), 1)
    except ValueError:
        page = 1

    try:
        page_size = int(request.args.get("page_size", str(PAGE_SIZE_DEFAULT)))
    except ValueError:
        page_size = PAGE_SIZE_DEFAULT
    page_size = max(1, min(page_size, PAGE_SIZE_MAX))

    action_filter = (request.args.get("action") or "").strip()
    email_filter = (request.args.get("email") or "").strip().lower()

    query = AuditLog.query
    if action_filter:
        query = query.filter(AuditLog.action.ilike(f"{action_filter}%"))
    if email_filter:
        query = query.filter(AuditLog.actor_email.ilike(f"%{email_filter}%"))

    total = query.count()

    offset = (page - 1) * page_size
    rows = (
        query.order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    has_next = offset + len(rows) < total
    has_prev = page > 1

    return render_template(
        "admin_audit.html",
        rows=rows,
        page=page,
        page_size=page_size,
        total=total,
        has_next=has_next,
        has_prev=has_prev,
        action_filter=action_filter,
        email_filter=email_filter,
    )


# ---------------------------------------------------------------------------
# Email templates — list + edit. Project brief, section 7.
# ---------------------------------------------------------------------------


@admin_bp.get("/email-templates")
@require_superadmin_2fa
def email_templates_list():
    """List every editable email template, alphabetised by key."""

    rows = EmailTemplate.query.order_by(EmailTemplate.key.asc()).all()
    return render_template("admin_email_templates.html", templates=rows)


def _load_template_or_404(key: str) -> EmailTemplate:
    template = EmailTemplate.query.filter_by(key=key).first()
    if template is None:
        abort(404)
    return template


@admin_bp.route("/email-templates/<key>", methods=["GET", "POST"])
@require_superadmin_2fa
def email_template_edit(key: str):
    """Edit one email template's subject / text body / HTML body."""

    template = _load_template_or_404(key)
    error: str | None = None
    preview_subject: str | None = None
    preview_text: str | None = None
    preview_html: str | None = None

    # Working copies of the form fields. We default to the persisted values
    # so a GET shows the current row, then overwrite from POST data so an
    # invalid submission (or a preview) does not lose the editor's edits.
    form_subject = template.subject
    form_body_text = template.body_text
    form_body_html = template.body_html or ""

    if request.method == "POST":
        action = (request.form.get("action") or "save").strip().lower()

        form_subject = (request.form.get("subject") or "").strip()
        form_body_text = request.form.get("body_text") or ""
        form_body_html = (request.form.get("body_html") or "").rstrip()
        normalized_html: str | None = form_body_html.strip() or None

        if not form_subject:
            error = "Subject must not be empty."
        elif not form_body_text.strip():
            error = "Plain-text body must not be empty (Mailgun requires it)."
        elif action == "preview":
            # Render the unsaved strings directly — no DB write — so editors
            # can iterate without polluting history with half-finished saves.
            try:
                preview_subject, preview_text, preview_html = render_email_strings(
                    subject=form_subject,
                    body_text=form_body_text,
                    body_html=normalized_html,
                    context=_preview_context(),
                )
            except Exception as err:  # noqa: BLE001 — show the editor the syntax error
                error = f"Template render failed: {err}"
        else:
            template.subject = form_subject
            template.body_text = form_body_text
            template.body_html = normalized_html
            template.updated_by_id = current_user.id
            db.session.commit()
            audit_record(
                "email_template.updated",
                status=AuditStatus.SUCCESS,
                target_type="email_template",
                target_id=template.id,
                context={"key": template.key},
                commit=True,
            )
            flash("Template saved.")
            return redirect(url_for("admin.email_template_edit", key=key))

    return render_template(
        "admin_email_template_edit.html",
        template=template,
        form_subject=form_subject,
        form_body_text=form_body_text,
        form_body_html=form_body_html,
        error=error,
        preview_subject=preview_subject,
        preview_text=preview_text,
        preview_html=preview_html,
    )


def _preview_context() -> dict[str, object]:
    """Stub values for every variable the seed templates use.

    Matches the sample context used by ``flask send-test-email`` so the editor
    sees consistent placeholders regardless of which template they pick.
    """

    return {
        "user_email": "preview@example.com",
        "organization_name": "Preview Organization",
        "login_url": "https://example.com/login",
        "reset_url": "https://example.com/reset/abc123",
        "expires_minutes": 30,
        "code": "123 456",
        "backup_name": "preview-backup",
        "completed_at": "2026-04-25 10:00:00 UTC",
        "size_human": "12.3 MB",
        "location": "/var/backups/pindora/preview.sql.gz",
        "failed_at": "2026-04-25 10:00:00 UTC",
        "error_message": "pg_dump: connection refused (preview)",
        "subject_line": "Preview admin notification",
        "message": "This is a preview message.",
    }


# ---------------------------------------------------------------------------
# Backups — list + manual trigger. Project brief, section 8.
# ---------------------------------------------------------------------------


@admin_bp.get("/backups")
@require_superadmin_2fa
def backups_list():
    """Show recent backups, newest first."""

    rows = (
        Backup.query.order_by(Backup.created_at.desc())
        .limit(100)
        .all()
    )
    return render_template("admin_backups.html", rows=rows)


@admin_bp.post("/backups/create")
@require_superadmin_2fa
def backups_create():
    """Run a manual backup synchronously and redirect back to the list.

    Backups are seconds-to-minutes; running the dump in-request keeps the
    feedback loop tight (the page either flashes "completed" with a size or
    "failed" with the error). For very large datasets a background job would
    be a sensible upgrade, but the call site here would not change.
    """

    try:
        backup = create_backup(
            trigger=BackupTrigger.MANUAL,
            actor_user_id=current_user.id,
        )
    except BackupError as err:
        flash(f"Backup failed: {err}")
        return redirect(url_for("admin.backups_list"))

    flash(f"Backup created: {backup.filename} ({backup.size_human}).")
    return redirect(url_for("admin.backups_list"))


@admin_bp.route("/backups/<int:backup_id>/restore", methods=["GET", "POST"])
@require_superadmin_2fa
def backups_restore(backup_id: int):
    """Restore the database from a previously taken backup.

    Per project brief section 8 the operator must confirm by re-entering
    their password and a fresh TOTP code before the destructive load runs.
    The view enforces that order: a GET shows the warning + form; the POST
    re-validates the credentials, takes a safe-copy of the current state,
    and then loads the chosen file inside a single transaction.
    """

    import pyotp

    from app.audit import record as audit_record_local  # alias for clarity
    from app.audit.models import AuditStatus as _AuditStatus
    from app.users.models import User

    backup = Backup.query.get(backup_id)
    if backup is None:
        abort(404)
    if backup.status != "success":
        abort(404)  # Only completed backups can be restored.

    error: str | None = None

    if request.method == "POST":
        password = request.form.get("password") or ""
        totp_code = (request.form.get("totp_code") or "").replace(" ", "").strip()

        # Re-fetch the user so we read the password hash and totp_secret as
        # they currently sit in the DB, not from the cached session object.
        user: User = User.query.get(current_user.id)

        # Step 1: password.
        if not user or not user.check_password(password):
            audit_record_local(
                "backup.restore.auth_failed",
                status=_AuditStatus.FAILURE,
                target_type="backup",
                target_id=backup.id,
                context={"stage": "password"},
                commit=True,
            )
            error = "Password did not match."
        # Step 2: 2FA.
        elif not user.totp_secret or not pyotp.TOTP(user.totp_secret).verify(
            totp_code, valid_window=1
        ):
            audit_record_local(
                "backup.restore.auth_failed",
                status=_AuditStatus.FAILURE,
                target_type="backup",
                target_id=backup.id,
                context={"stage": "2fa"},
                commit=True,
            )
            error = "Verification code did not match."
        else:
            # Step 3: safe-copy + restore.
            try:
                safe_copy = restore_backup(
                    filename=backup.filename,
                    actor_user_id=current_user.id,
                )
            except BackupError as err:
                flash(f"Restore failed: {err}")
                return redirect(url_for("admin.backups_list"))

            flash(
                f"Restore complete from {backup.filename}. A safe-copy of the "
                f"previous state was saved as {safe_copy.filename}."
            )
            return redirect(url_for("admin.backups_list"))

    return render_template(
        "admin_backup_restore.html",
        backup=backup,
        error=error,
    )


# ---------------------------------------------------------------------------
# Settings — list + edit + create. Project brief, section 9.
# ---------------------------------------------------------------------------


@admin_bp.get("/settings")
@require_superadmin_2fa
def settings_list():
    """Show every application setting, alphabetical, secrets masked."""

    rows = settings_service.get_all()
    return render_template(
        "admin_settings.html",
        rows=rows,
        mask=settings_service.mask_for_display,
    )


@admin_bp.route("/settings/new", methods=["GET", "POST"])
@require_superadmin_2fa
def settings_new():
    """Create a new setting row.

    Key is required and must be unique. Type is required and immutable
    afterwards — changing a setting's type is a separate (manual) operation
    because it implies a value migration.
    """

    error: str | None = None

    form = {
        "key": "",
        "value": "",
        "type": SettingType.STRING,
        "description": "",
        "is_secret": False,
    }

    if request.method == "POST":
        form["key"] = (request.form.get("key") or "").strip()
        form["value"] = request.form.get("value") or ""
        form["type"] = (request.form.get("type") or SettingType.STRING).strip()
        form["description"] = (request.form.get("description") or "").strip()
        form["is_secret"] = bool(request.form.get("is_secret"))

        if not form["key"]:
            error = "Key is required."
        elif form["type"] not in SettingType.ALL:
            error = f"Type must be one of: {', '.join(SettingType.ALL)}."
        elif settings_service.find(form["key"]) is not None:
            error = f"A setting with key {form['key']!r} already exists."
        else:
            try:
                settings_service.set_value(
                    form["key"],
                    _coerce_form_value(form["value"], form["type"]),
                    type_=form["type"],
                    description=form["description"],
                    is_secret=form["is_secret"],
                    actor_user_id=current_user.id,
                )
            except settings_service.SettingValueError as err:
                error = f"Invalid value for type {form['type']!r}: {err}"
            else:
                flash(f"Setting {form['key']!r} created.")
                return redirect(url_for("admin.settings_edit", key=form["key"]))

    return render_template(
        "admin_settings_new.html",
        form=form,
        types=SettingType.ALL,
        error=error,
    )


@admin_bp.route("/settings/<key>", methods=["GET", "POST"])
@require_superadmin_2fa
def settings_edit(key: str):
    """Edit one setting — value, description, is_secret. Key + type are stable."""

    row = settings_service.find(key)
    if row is None:
        abort(404)

    error: str | None = None
    # Pre-fill the value field with the *masked* display when this is a
    # secret, so the page never sends the live secret back over the wire on
    # GET. The user must re-enter the secret to update it.
    if row.is_secret:
        form_value = ""
    else:
        form_value = settings_service.mask_for_display(row)

    form_description = row.description
    form_is_secret = row.is_secret

    if request.method == "POST":
        form_value = request.form.get("value") or ""
        form_description = (request.form.get("description") or "").strip()
        form_is_secret = bool(request.form.get("is_secret"))

        # If the row is currently a secret and the user submits an empty
        # value, treat that as "leave value unchanged" rather than wiping it
        # — the masked display means the textarea was empty on GET. We re-
        # read through the public service API instead of touching the row
        # directly so the rule "always go through the service" holds.
        if row.is_secret and form_value == "":
            new_value = settings_service.get(row.key)
        else:
            try:
                new_value = _coerce_form_value(form_value, row.type)
            except (ValueError, settings_service.SettingValueError) as err:
                error = f"Invalid value for type {row.type!r}: {err}"
                new_value = None  # silence type-checker

        if error is None:
            try:
                settings_service.set_value(
                    row.key,
                    new_value,
                    description=form_description,
                    is_secret=form_is_secret,
                    actor_user_id=current_user.id,
                )
            except settings_service.SettingValueError as err:
                error = str(err)
            else:
                flash("Setting saved.")
                return redirect(url_for("admin.settings_edit", key=row.key))

    return render_template(
        "admin_settings_edit.html",
        setting=row,
        form_value=form_value,
        form_description=form_description,
        form_is_secret=form_is_secret,
        error=error,
    )


def _coerce_form_value(raw: str, type_: str):
    """Translate a form string into the native value the service expects."""

    if type_ == SettingType.STRING:
        return raw
    if type_ == SettingType.INT:
        if raw.strip() == "":
            return 0
        return int(raw)  # ValueError surfaces in the caller
    if type_ == SettingType.BOOL:
        return raw.strip().lower() in {"true", "1", "yes", "on"}
    if type_ == SettingType.JSON:
        # Pass the raw string through; ``set_value`` will round-trip via JSON.
        # We delegate parsing to the service so error messages stay consistent.
        import json as _json

        return _json.loads(raw) if raw.strip() else None
    return raw
