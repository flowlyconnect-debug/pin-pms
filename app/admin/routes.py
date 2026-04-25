"""Admin-only views — audit log browser and email-template editor.

All routes in this blueprint require an authenticated superadmin whose TOTP
2FA session is verified. Reuses the decorator declared in :mod:`app.auth.routes`
so the 2FA gate stays in a single place.
"""
from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.audit import record as audit_record
from app.audit.models import AuditLog, AuditStatus
from app.auth.routes import require_superadmin_2fa
from app.email.models import EmailTemplate
from app.email.services import render_strings as render_email_strings
from app.extensions import db


PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 200


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
