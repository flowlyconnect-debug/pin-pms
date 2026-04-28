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
from typing import Any, Mapping, Optional

import requests
from flask import current_app

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.email.models import EmailTemplate, OutgoingEmail, OutgoingEmailStatus
from app.email.templates import EmailTemplateNotFound, render_template_for
from app.extensions import db

logger = logging.getLogger(__name__)


def _build_from_header(app_config: Mapping[str, Any]) -> str:
    # Prefer brief-style names, fall back to legacy MAIL_FROM* aliases.
    name = (
        app_config.get("MAILGUN_FROM_NAME")
        or app_config.get("MAIL_FROM_NAME")
        or "Pindora PMS"
    )
    addr = (
        app_config.get("MAILGUN_FROM_EMAIL")
        or app_config.get("MAIL_FROM")
        or "noreply@example.com"
    )
    return f"{name} <{addr}>"


def send_template(key: str, *, to: str, context: Optional[Mapping[str, Any]] = None) -> bool:
    """Queue an outbound email row and return immediately."""
    context = dict(context or {})
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
            context={"key": key, "to": to, "stage": "render", "error": str(err)},
            commit=True,
        )
        return False

    queued = OutgoingEmail(
        to=to,
        template_key=key,
        context_json=context,
        subject_snapshot=rendered.subject,
        status=OutgoingEmailStatus.PENDING,
    )
    try:
        db.session.add(queued)
        db.session.commit()
        return True
    except Exception as err:  # noqa: BLE001
        db.session.rollback()
        logger.exception("Failed to queue email template %s", key)
        audit_record(
            "email.failed",
            status=AuditStatus.FAILURE,
            target_type="email_template",
            context={"key": key, "to": to, "stage": "queue", "error": str(err)},
            commit=True,
        )
        return False


def send_template_sync(
    key: str,
    *,
    to: str,
    context: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Render and send ``key`` to ``to`` in the current thread."""
    context = dict(context or {})
    try:
        rendered = render_template_for(key, context)
    except EmailTemplateNotFound:
        raise
    except Exception as err:  # noqa: BLE001
        logger.exception("Failed to render email template %s", key)
        audit_record(
            "email.failed",
            status=AuditStatus.FAILURE,
            target_type="email_template",
            context={"key": key, "to": to, "stage": "render", "error": str(err)},
            commit=True,
        )
        return False
    return _send_rendered(key=key, to=to, rendered=rendered)


def _send_rendered(*, key: str, to: str, rendered) -> bool:
    cfg = current_app.config
    log_only = (
        bool(cfg.get("MAIL_DEV_LOG_ONLY"))
        or not (cfg.get("MAILGUN_API_KEY") or "").strip()
    )

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
        resp = requests.post(
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
                description=t["description"],
                available_variables=t["available_variables"],
            )
        )
    db.session.commit()
    logger.info("Seeded missing email templates: %s", [t["key"] for t in new_rows])
