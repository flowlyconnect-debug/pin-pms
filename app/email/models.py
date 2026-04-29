"""Database-backed email templates.

The project brief (section 7) requires six editable email templates that a
superadmin can change at runtime. Storing them in the database — instead of as
Jinja files on disk — means edits go through the audit log, ship without a
deploy, and are easy to surface in an admin UI.

Each row holds:

* ``key``                    — the stable identifier sent by code (e.g.
                               ``welcome_email``). Never changed once seeded.
* ``subject``                — Jinja template for the subject line.
* ``body_text``              — required plain-text body (Jinja). Mailgun
                               always needs a text body for accessibility.
* ``body_html``              — optional HTML body (Jinja). Sent as the
                               multipart ``html`` part if present.
* ``description``            — human description shown in the admin UI.
* ``available_variables``    — JSON list of variable names that callers
                               promise to provide. The admin UI displays this
                               so editors know which placeholders are safe.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


class EmailTemplate(db.Model):
    __tablename__ = "email_templates"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    subject = db.Column(db.String(255), nullable=False)
    body_text = db.Column(db.Text, nullable=False)
    body_html = db.Column(db.Text, nullable=True)
    text_content = db.Column(db.Text, nullable=False, default="")
    html_content = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(255), nullable=False, default="")
    available_variables = db.Column(db.JSON, nullable=False, default=list)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    updated_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic only
        return f"<EmailTemplate {self.key}>"

    @property
    def effective_text_content(self) -> str:
        return self.text_content or self.body_text

    @property
    def effective_html_content(self) -> str | None:
        return self.html_content if self.html_content is not None else self.body_html


# ---------------------------------------------------------------------------
# Template keys exposed as constants so call
# sites do not pass raw strings around.
# ---------------------------------------------------------------------------


class TemplateKey:
    WELCOME_EMAIL = "welcome_email"
    PASSWORD_RESET = "password_reset"
    LOGIN_2FA_CODE = "login_2fa_code"
    BACKUP_COMPLETED = "backup_completed"
    BACKUP_FAILED = "backup_failed"
    ADMIN_NOTIFICATION = "admin_notification"
    RESERVATION_CONFIRMATION = "reservation_confirmation"
    RESERVATION_CANCELLED = "reservation_cancelled"
    INVOICE_CREATED = "invoice_created"
    INVOICE_OVERDUE = "invoice_overdue"
    INVOICE_PAID = "invoice_paid"

    ALL = (
        WELCOME_EMAIL,
        PASSWORD_RESET,
        LOGIN_2FA_CODE,
        BACKUP_COMPLETED,
        BACKUP_FAILED,
        ADMIN_NOTIFICATION,
        RESERVATION_CONFIRMATION,
        RESERVATION_CANCELLED,
        INVOICE_CREATED,
        INVOICE_OVERDUE,
        INVOICE_PAID,
    )


class OutgoingEmailStatus:
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"

    ALL = (PENDING, SENT, FAILED)


class OutgoingEmail(db.Model):
    __tablename__ = "outgoing_emails"

    id = db.Column(db.Integer, primary_key=True)
    to = db.Column(db.String(255), nullable=False, index=True)
    template_key = db.Column(db.String(64), nullable=False, index=True)
    context_json = db.Column(db.JSON, nullable=False, default=dict)
    subject_snapshot = db.Column(db.String(255), nullable=True)
    status = db.Column(
        db.String(16),
        nullable=False,
        default=OutgoingEmailStatus.PENDING,
        index=True,
    )
    attempts = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.Text, nullable=True)
    scheduled_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
