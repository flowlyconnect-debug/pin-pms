from __future__ import annotations

import pyotp
from functools import wraps
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.auth.routes import require_superadmin_2fa
from app.backups.models import Backup, BackupTrigger
from app.backups.services import BackupError, create_backup, restore_backup
from app.users.models import User

backups_admin_bp = Blueprint("backups_admin", __name__)


def check_impersonation_blocked(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        from flask import session
        if session.get("impersonator_user_id"):
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped


@backups_admin_bp.get("")
@require_superadmin_2fa
def backups_list():
    """Show recent backups, newest first."""

    rows = (
        Backup.query.order_by(Backup.created_at.desc())
        .limit(100)
        .all()
    )
    return render_template("admin_backups.html", rows=rows)


@backups_admin_bp.post("/create")
@require_superadmin_2fa
def backups_create():
    """Run a manual backup synchronously and redirect back to the list."""

    try:
        backup = create_backup(
            trigger=BackupTrigger.MANUAL,
            actor_user_id=current_user.id,
        )
    except BackupError:
        flash("Varmuuskopiointi epäonnistui.")
        return redirect(url_for("backups_admin.backups_list"))

    flash(f"Varmuuskopio luotu: {backup.filename} ({backup.size_human}).")
    return redirect(url_for("backups_admin.backups_list"))


@backups_admin_bp.get("/<int:backup_id>/download")
@require_superadmin_2fa
def backups_download(backup_id: int):
    """Stream a backup file to the superadmin's browser."""

    backup = Backup.query.get(backup_id)
    if backup is None or backup.status != "success":
        abort(404)

    backup_dir = current_app.config.get("BACKUP_DIR", "/var/backups/pindora")
    audit_record(
        "backup.downloaded",
        status=AuditStatus.SUCCESS,
        target_type="backup",
        target_id=backup.id,
        context={"filename": backup.filename},
        commit=True,
    )
    return send_from_directory(
        directory=backup_dir,
        path=backup.filename,
        as_attachment=True,
        download_name=backup.filename,
    )


@backups_admin_bp.route("/<int:backup_id>/restore", methods=["GET", "POST"])
@require_superadmin_2fa
@check_impersonation_blocked
def backups_restore(backup_id: int):
    """Restore the database from a previously taken backup."""

    backup = Backup.query.get(backup_id)
    if backup is None or backup.status != "success":
        abort(404)

    error: str | None = None
    if request.method == "POST":
        password = request.form.get("password") or ""
        totp_code = (request.form.get("totp_code") or "").replace(" ", "").strip()
        user: User = User.query.get(current_user.id)

        if not user or not user.check_password(password):
            audit_record(
                "backup.restore.auth_failed",
                status=AuditStatus.FAILURE,
                target_type="backup",
                target_id=backup.id,
                context={"stage": "password"},
                commit=True,
            )
            error = "Salasana ei täsmännyt."
        elif not user.totp_secret or not pyotp.TOTP(user.totp_secret).verify(
            totp_code, valid_window=1
        ):
            audit_record(
                "backup.restore.auth_failed",
                status=AuditStatus.FAILURE,
                target_type="backup",
                target_id=backup.id,
                context={"stage": "2fa"},
                commit=True,
            )
            error = "Vahvistuskoodi ei täsmännyt."
        else:
            try:
                safe_copy = restore_backup(
                    filename=backup.filename,
                    actor_user_id=current_user.id,
                )
            except BackupError:
                flash("Palautus epäonnistui.")
                return redirect(url_for("backups_admin.backups_list"))

            flash(
                f"Palautus suoritettu varmuuskopiosta {backup.filename}. "
                f"Edellinen tila tallennettiin turvakopiona nimellä {safe_copy.filename}."
            )
            return redirect(url_for("backups_admin.backups_list"))

    return render_template(
        "admin_backup_restore.html",
        backup=backup,
        error=error,
    )
