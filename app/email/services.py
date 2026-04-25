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
from jinja2.sandbox import SandboxedEnvironment

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.email.models import EmailTemplate

logger = logging.getLogger(__name__)

# Sandboxed Jinja shared across calls. ``autoescape`` is False because the
# text body is plain text; the HTML body is autoescaped per-call when present.
_TEXT_ENV = SandboxedEnvironment(autoescape=False, trim_blocks=False, lstrip_blocks=False)
_HTML_ENV = SandboxedEnvironment(autoescape=True, trim_blocks=False, lstrip_blocks=False)


class EmailTemplateNotFound(LookupError):
    """Raised when the caller requests a template key that does not exist.

    This is a programmer error — every call site should reference one of the
    keys in :class:`app.email.models.TemplateKey`.
    """


def _render(template_str: str, context: Mapping[str, Any], *, html: bool) -> str:
    env = _HTML_ENV if html else _TEXT_ENV
    return env.from_string(template_str).render(**context)


def _build_from_header(app_config: Mapping[str, Any]) -> str:
    name = app_config.get("MAIL_FROM_NAME") or "Pindora PMS"
    addr = app_config.get("MAIL_FROM") or "noreply@example.com"
    return f"{name} <{addr}>"


def render_strings(
    *,
    subject: str,
    body_text: str,
    body_html: Optional[str],
    context: Mapping[str, Any],
) -> tuple[str, str, Optional[str]]:
    """Render arbitrary template strings — used by the admin "preview" path.

    Decoupling this from the DB lookup means the editor can preview unsaved
    changes without round-tripping through the session.
    """

    merged: dict[str, Any] = {"from_name": current_app.config.get("MAIL_FROM_NAME", "")}
    merged.update(dict(context))

    rendered_subject = _render(subject, merged, html=False).strip()
    rendered_text = _render(body_text, merged, html=False)
    rendered_html = _render(body_html, merged, html=True) if body_html else None
    return rendered_subject, rendered_text, rendered_html


def render_template(key: str, context: Mapping[str, Any]) -> tuple[str, str, Optional[str]]:
    """Render the named DB template and return ``(subject, body_text, body_html)``.

    Used by :func:`send_template`. Raises :class:`EmailTemplateNotFound` if no
    row matches ``key``.
    """

    template: Optional[EmailTemplate] = EmailTemplate.query.filter_by(key=key).first()
    if template is None:
        raise EmailTemplateNotFound(f"Email template '{key}' is not seeded.")

    return render_strings(
        subject=template.subject,
        body_text=template.body_text,
        body_html=template.body_html,
        context=context,
    )


def send_template(
    key: str,
    *,
    to: str,
    context: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Render ``key`` and send the result to ``to``. Returns success."""

    context = dict(context or {})

    try:
        subject, body_text, body_html = render_template(key, context)
    except EmailTemplateNotFound:
        # Programmer error — re-raise so the bug is visible in tests/CI rather
        # than silently swallowed.
        raise
    except Exception as err:  # noqa: BLE001 — we want to log every render failure
        logger.exception("Failed to render email template %s", key)
        audit_record(
            "email.failed",
            status=AuditStatus.FAILURE,
            target_type="email_template",
            context={"key": key, "to": to, "stage": "render", "error": str(err)},
            commit=True,
        )
        return False

    cfg = current_app.config
    log_only = bool(cfg.get("MAIL_DEV_LOG_ONLY")) or not cfg.get("MAILGUN_API_KEY")

    if log_only:
        logger.info(
            "[email:dev-log-only] key=%s to=%s subject=%s\n--- text ---\n%s%s",
            key,
            to,
            subject,
            body_text,
            f"\n--- html ---\n{body_html}" if body_html else "",
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
        "subject": subject,
        "text": body_text,
    }
    if body_html:
        payload["html"] = body_html

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
