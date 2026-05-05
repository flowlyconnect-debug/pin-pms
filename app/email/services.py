"""Outbound email service.

Looks up an editable template by key, renders subject/body with the supplied
context, and posts the result to the Mailgun HTTP API. Every send is recorded
in the audit log so superadmins can answer "did this user actually get the
email" months later.

Design choices
--------------

* **Sandboxed Jinja.** Templates are user-editable (superadmins can change
  them at runtime), so we render through ``jinja2.sandbox.SandboxedEnvironment``
  to stop the template engine from being weaponised into reading attributes
  off arbitrary Python objects.
* **Never raises in normal use.** ``send_template`` returns ``True`` on
  success, ``False`` on any handled failure, and only raises for genuinely
  unrecoverable programmer errors (e.g. missing template). The caller is
  expected to react to ``False`` by surfacing a flash / API error, not by
  letting the request 500.
* **Dev mode.** When ``MAIL_DEV_LOG_ONLY`` is true (or the API key is
  missing), the rendered email is logged at INFO level and the function
  returns success without hitting Mailgun. Production deployments must keep
  ``MAIL_DEV_LOG_ONLY=0`` and provide a real API key.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import requests
from flask import current_app

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.core.telemetry import trace_http_call, traced
from app.email.models import EmailQueueItem, EmailTemplate, OutgoingEmailStatus
from app.email.templates import (
    EmailTemplateNotFound,
    RenderedEmail,
    render_template_for,
    validate_context,
)
from app.extensions import db

logger = logging.getLogger(__name__)
_CONTEXT_SECRET_KEYS = ("password", "token", "api_key", "secret", "authorization")


class EmailServiceError(Exception):
    """Handled email-service error with safe, user-facing message."""

    def __init__(self, public_message: str, *, internal_detail: str | None = None):
        super().__init__(public_message)
        self.public_message = public_message
        self.internal_detail = internal_detail


@dataclass(frozen=True)
class EmailServiceResult:
    success: bool
    message: str


def _build_from_header(app_config: Mapping[str, Any]) -> str:
    # Prefer brief-style names, fall back to legacy MAIL_FROM* aliases.
    name = app_config.get("MAILGUN_FROM_NAME") or app_config.get("MAIL_FROM_NAME") or "Pin PMS"
    addr = (
        app_config.get("MAILGUN_FROM_EMAIL") or app_config.get("MAIL_FROM") or "noreply@example.com"
    )
    return f"{name} <{addr}>"


def _safe_preview_context() -> dict[str, object]:
    return {
        "user_email": "demo@example.com",
        "organization_name": "Demo Organisaatio",
        "login_url": "https://example.com/login",
        "reset_url": "https://example.com/reset/demo-token",
        "expires_minutes": 30,
        "code": "123 456",
        "backup_name": "demo-backup",
        "completed_at": "2026-04-25 10:00:00 UTC",
        "size_human": "12.3 MB",
        "location": "/var/backups/pindora/demo.sql.gz",
        "failed_at": "2026-04-25 10:00:00 UTC",
        "error_message": "demo error",
        "subject_line": "Demo ilmoitus",
        "message": "Tama on turvallinen esikatseluviesti.",
        "from_name": "Pin PMS",
        "reservation_id": 1001,
        "unit_name": "A-101",
        "start_date": "2026-05-01",
        "end_date": "2026-05-05",
        "invoice_number": "INV-1001",
        "amount": "100.00",
        "currency": "EUR",
        "due_date": "2026-05-10",
        "description": "Testilaskun kuvaus",
    }


def _is_valid_email(value: str) -> bool:
    addr = (value or "").strip()
    if not addr or " " in addr:
        return False
    if "@" not in addr:
        return False
    local, _, domain = addr.partition("@")
    return bool(local and domain and "." in domain)


def _mask_email(value: str) -> str:
    addr = (value or "").strip()
    if "@" not in addr:
        return "***"
    local, _, domain = addr.partition("@")
    if len(local) <= 2:
        visible_local = local[:1] + "*"
    else:
        visible_local = local[:2] + "***"
    return f"{visible_local}@{domain}"


def _safe_error_text(err: object) -> str:
    return str(err or "")[:240]


def _sanitize_context(context: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in dict(context or {}).items():
        lowered = str(key).strip().lower()
        if any(part in lowered for part in _CONTEXT_SECRET_KEYS):
            continue
        safe[key] = value
    return safe


def render_template(template_key: str, context: Mapping[str, Any]) -> RenderedEmail:
    missing = validate_context(template_key, dict(context))
    if missing:
        raise EmailServiceError(
            "Pohjan renderointi epaonnistui: puuttuvia muuttujia.",
            internal_detail=", ".join(missing),
        )
    try:
        return render_template_for(template_key, dict(context))
    except EmailTemplateNotFound as err:
        raise EmailServiceError("Sahkopostipohjaa ei loytynyt.", internal_detail=str(err)) from err
    except Exception as err:  # noqa: BLE001
        raise EmailServiceError(
            "Pohjan renderointi epaonnistui.",
            internal_detail=type(err).__name__,
        ) from err


def send_email(to: str, subject: str, html: str | None, text: str) -> EmailServiceResult:
    if not _is_valid_email(to):
        raise EmailServiceError("Vastaanottajan sahkoposti on virheellinen.")
    rendered = RenderedEmail(subject=subject, html=html, text=text)
    ok = _send_rendered(key="custom", to=to, rendered=rendered)
    if not ok:
        raise EmailServiceError("Sahkopostin lahetys epaonnistui.")
    return EmailServiceResult(success=True, message="Sahkoposti lahetetty.")


def send_template_email(
    template_key: str, to: str, context: Mapping[str, Any]
) -> EmailServiceResult:
    rendered = render_template(template_key, context)
    return send_email(to=to, subject=rendered.subject, html=rendered.html, text=rendered.text)


def send_test_template_email(template_key: str, to: str, actor_user) -> EmailServiceResult:
    context = _safe_preview_context()
    actor_email = getattr(actor_user, "email", None)
    if actor_email:
        context["user_email"] = actor_email
    return send_template_email(template_key, to, context)


@traced("email.send_template")
def send_template(key: str, *, to: str, context: Optional[Mapping[str, Any]] = None) -> bool:
    """Queue an outbound email row and return immediately."""
    cfg = current_app.config
    context = _sanitize_context(context or {})
    if bool(cfg.get("MAIL_DEV_LOG_ONLY")):
        try:
            rendered = render_template_for(key, context)
        except EmailTemplateNotFound:
            raise
        except Exception as err:  # noqa: BLE001
            logger.exception("Failed to render email template %s in dev-log-only mode", key)
            audit_record(
                "email.failed",
                status=AuditStatus.FAILURE,
                target_type="email_template",
                context={"key": key, "to": _mask_email(to), "stage": "render", "error": _safe_error_text(err)},
                commit=True,
            )
            return False
        return _send_rendered(key=key, to=to, rendered=rendered)

    try:
        rendered = render_template_for(key, context)
    except EmailTemplateNotFound:
        raise
    except Exception as err:  # noqa: BLE001 — we want to log every render failure
        logger.exception("Failed to render email template %s for queueing", key)
        audit_record(
            "email.failed",
            status=AuditStatus.FAILURE,
            target_type="email_template",
            context={"key": key, "to": _mask_email(to), "stage": "render", "error": _safe_error_text(err)},
            commit=True,
        )
        return False

    queued = EmailQueueItem(
        to=to,
        recipient_email=to,
        organization_id=context.get("organization_id"),
        template_key=key,
        context_json=context,
        subject_snapshot=rendered.subject,
        status=OutgoingEmailStatus.PENDING,
        attempts=0,
        attempt_count=0,
        scheduled_at=datetime.now(timezone.utc),
        next_attempt_at=datetime.now(timezone.utc),
    )
    try:
        db.session.add(queued)
        db.session.commit()
        audit_record(
            "email.queued",
            status=AuditStatus.SUCCESS,
            organization_id=queued.organization_id,
            target_type="email_queue",
            target_id=queued.id,
            metadata={"template_key": key, "recipient_email": _mask_email(to), "status": queued.status},
            commit=True,
        )
        return True
    except Exception as err:  # noqa: BLE001
        db.session.rollback()
        logger.exception("Failed to queue email template %s", key)
        audit_record(
            "email.failed",
            status=AuditStatus.FAILURE,
            target_type="email_template",
            context={"key": key, "to": _mask_email(to), "stage": "queue", "error": _safe_error_text(err)},
            commit=True,
        )
        return False


@traced("email.send_template_now")
def send_template_now(
    key: str,
    *,
    to: str,
    context: Optional[Mapping[str, Any]] = None,
) -> bool:
    context = _sanitize_context(context or {})
    try:
        rendered = render_template_for(key, context)
    except EmailTemplateNotFound:
        raise
    except Exception as err:  # noqa: BLE001
        logger.exception("Failed to render email template %s for immediate send", key)
        audit_record(
            "email.failed",
            status=AuditStatus.FAILURE,
            target_type="email_template",
            context={"key": key, "to": _mask_email(to), "stage": "render", "error": _safe_error_text(err)},
            commit=True,
        )
        return False
    return _send_rendered(key=key, to=to, rendered=rendered)


@traced("email.send_template_sync")
def send_template_sync(
    key: str,
    *,
    to: str,
    context: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Render and send ``key`` to ``to`` in the current thread."""
    context = _sanitize_context(context or {})
    try:
        return send_template_now(key, to=to, context=context)
    except EmailTemplateNotFound:
        raise
    except EmailServiceError as err:
        logger.warning("Template sync send failed for %s: %s", key, err.public_message)
        audit_record(
            "email.failed",
            status=AuditStatus.FAILURE,
            target_type="email_template",
            context={"key": key, "to": _mask_email(to), "stage": "service", "error": err.public_message},
            commit=True,
        )
        return False


def _send_rendered(*, key: str, to: str, rendered) -> bool:
    cfg = current_app.config
    log_only = bool(cfg.get("MAIL_DEV_LOG_ONLY")) or not (cfg.get("MAILGUN_API_KEY") or "").strip()

    if log_only:
        html_part = f"\n--- html ---\n{rendered.html}" if rendered.html else ""
        logger.info(
            f"[email:dev-log-only] key={key} to={to} subject={rendered.subject}\n"
            f"--- text ---\n{rendered.text}{html_part}"
        )
        audit_record(
            "email.sent",
            status=AuditStatus.SUCCESS,
            target_type="email_template",
            context={"key": key, "to": to, "transport": "dev_log_only"},
            commit=True,
        )
        return True

    domain = cfg.get("MAILGUN_DOMAIN") or ""
    base_url = (cfg.get("MAILGUN_BASE_URL") or "https://api.mailgun.net/v3").rstrip("/")
    if not domain:
        logger.error("MAILGUN_DOMAIN is not configured; cannot send '%s'", key)
        audit_record(
            "email.failed",
            status=AuditStatus.FAILURE,
            target_type="email_template",
            context={"key": key, "to": to, "stage": "config", "error": "missing MAILGUN_DOMAIN"},
            commit=True,
        )
        return False

    payload = {
        "from": _build_from_header(cfg),
        "to": to,
        "subject": rendered.subject,
        "text": rendered.text,
    }
    if rendered.html:
        payload["html"] = rendered.html

    try:
        resp = trace_http_call(
            "mailgun.send_message",
            requests.post,
            f"{base_url}/{domain}/messages",
            auth=("api", cfg["MAILGUN_API_KEY"]),
            data=payload,
            timeout=15,
        )
    except requests.RequestException as err:
        logger.exception("Mailgun request failed for template %s", key)
        audit_record(
            "email.failed",
            status=AuditStatus.FAILURE,
            target_type="email_template",
            context={"key": key, "to": to, "stage": "transport", "error": str(err)},
            commit=True,
        )
        return False

    if resp.status_code >= 300:
        # Mailgun returns 4xx / 5xx with a JSON body containing ``message``.
        snippet = resp.text[:300] if resp.text else ""
        logger.error(
            "Mailgun rejected template %s for %s: %s %s",
            key,
            to,
            resp.status_code,
            snippet,
        )
        audit_record(
            "email.failed",
            status=AuditStatus.FAILURE,
            target_type="email_template",
            context={
                "key": key,
                "to": to,
                "stage": "mailgun",
                "status": resp.status_code,
                "response": snippet,
            },
            commit=True,
        )
        return False

    audit_record(
        "email.sent",
        status=AuditStatus.SUCCESS,
        target_type="email_template",
        context={"key": key, "to": to, "transport": "mailgun"},
        commit=True,
    )
    return True


def update_email_template_admin(
    *,
    template: EmailTemplate,
    subject: str,
    body_text: str,
    body_html: str | None,
    actor_id: int,
) -> None:
    """Persist superadmin edits to a template row and write the audit event."""

    from app.audit.models import ActorType

    normalized_html = (body_html or "").strip() or None
    template.subject = subject.strip()
    template.body_text = body_text
    template.body_html = normalized_html
    template.text_content = body_text
    template.html_content = normalized_html
    template.updated_by_id = actor_id
    db.session.commit()

    audit_record(
        "email_template.update",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=actor_id,
        target_type="email_template",
        target_id=template.id,
        context={"template_key": template.key},
        commit=True,
    )


def ensure_seed_templates() -> None:
    """Insert any missing default templates.

    Called once at app start so a fresh database (or a new template added in
    code after the initial migration) does not surprise the runtime with a
    missing key. Existing rows are *not* overwritten — admin edits are
    preserved.
    """

    from app.email.seed_data import SEED_TEMPLATES
    from app.extensions import db

    existing_keys = {row.key for row in EmailTemplate.query.all()}
    new_rows = [t for t in SEED_TEMPLATES if t["key"] not in existing_keys]
    if not new_rows:
        return

    for t in new_rows:
        db.session.add(
            EmailTemplate(
                key=t["key"],
                subject=t["subject"],
                body_text=t["body_text"],
                body_html=t["body_html"],
                text_content=t["body_text"],
                html_content=t["body_html"],
                description=t["description"],
                available_variables=t["available_variables"],
            )
        )
    db.session.commit()
    logger.info("Seeded missing email templates: %s", [t["key"] for t in new_rows])
