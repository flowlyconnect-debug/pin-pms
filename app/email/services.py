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
import threading
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

    merged: dict[str, Any] = {
        "from_name": (
            current_app.config.get("MAILGUN_FROM_NAME")
            or current_app.config.get("MAIL_FROM_NAME")
            or ""
        )
    }
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
    async_: bool | None = None,
) -> bool:
    """Render ``key`` and send the result to ``to``. Returns success.

    Parameters
    ----------
    async_ :
        When True, the Mailgun HTTP call runs in a daemon background
        thread so the request that triggered the email returns
        immediately. This is the recommended path for user-facing flows
        (login emails, password resets, notifications) where Mailgun's
        latency would otherwise block the response. Defaults to True
        outside of tests; tests force synchronous behaviour so they can
        assert on the rendered output deterministically.

        Set to False to force synchronous behaviour even in production
        (e.g. CLI ``send-test-email`` wants to surface failures right
        away).
    """

    context = dict(context or {})

    cfg = current_app.config
    if async_ is None:
        # Default: synchronous in tests / dev-log-only mode (so behaviour is
        # observable), asynchronous in real deployments.
        async_ = not cfg.get("TESTING") and not cfg.get("MAIL_DEV_LOG_ONLY")

    if async_:
        # Capture the application object before launching the thread so the
        # daemon has a working app context independent of the request.
        app = current_app._get_current_object()  # type: ignore[attr-defined]
        thread = threading.Thread(
            target=_send_template_in_thread,
            args=(app, key, to, context),
            daemon=True,
            name=f"email-{key}",
        )
        thread.start()
        return True

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
    log_only = (
        bool(cfg.get("TESTING"))
        or bool(cfg.get("MAIL_DEV_LOG_ONLY"))
        or not (cfg.get("MAILGUN_API_KEY") or "").strip()
    )

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


def _send_template_in_thread(app, key: str, to: str, context: dict) -> None:
    """Re-enter the app context inside the worker thread and run the send.

    Errors are logged but never propagated — the calling request thread has
    already returned to the user.
    """

    try:
        with app.app_context():
            send_template(key, to=to, context=context, async_=False)
    except Exception:  # noqa: BLE001 — background thread must not crash the worker
        logger.exception("Background email send failed for template %s", key)


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
