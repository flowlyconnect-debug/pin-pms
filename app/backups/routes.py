from __future__ import annotations

from functools import wraps
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user

from app.auth.routes import require_superadmin_2fa
from app.backups.models import Backup, BackupTrigger
from app.backups.services import (
    BackupError,
    create_backup,
    list_backups_for_admin,
    record_backup_download_audit,
    restore_backup,
    verify_backup_restore_credentials,
)
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

    rows = list_backups_for_admin(limit=100)
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
    record_backup_download_audit(backup=backup)
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
        user: User | None = User.query.get(current_user.id)
        auth = verify_backup_restore_credentials(
            user=user,
            password=password,
            totp_code=totp_code,
            backup_id=backup.id,
        )
        if auth == "password":
            error = "Salasana ei täsmännyt."
        elif auth == "totp":
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
