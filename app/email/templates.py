from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from flask import current_app
from jinja2.sandbox import SandboxedEnvironment

from app.email.models import EmailTemplate
from app.email.seed_data import SEED_TEMPLATES

_TEXT_ENV = SandboxedEnvironment(autoescape=False, trim_blocks=False, lstrip_blocks=False)
_HTML_ENV = SandboxedEnvironment(autoescape=True, trim_blocks=False, lstrip_blocks=False)


class EmailTemplateNotFound(LookupError):
    """Raised when the requested email template key does not exist."""


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: Optional[str]
    text: str


def _render(template_str: str, context: Mapping[str, Any], *, html: bool) -> str:
    env = _HTML_ENV if html else _TEXT_ENV
    return env.from_string(template_str).render(**context)


def _from_name() -> str:
    return (
        current_app.config.get("MAILGUN_FROM_NAME")
        or current_app.config.get("MAIL_FROM_NAME")
        or ""
    )


def _lookup_template(key: str) -> EmailTemplate:
    template = EmailTemplate.query.filter_by(key=key).first()
    if template is None:
        raise EmailTemplateNotFound(f"Email template '{key}' is not seeded.")
    return template


def _seed_available_variables(key: str) -> list[str]:
    for seed in SEED_TEMPLATES:
        if seed["key"] == key:
            return list(seed.get("available_variables") or [])
    return []


def available_variables_for(key: str) -> list[str]:
    template = EmailTemplate.query.filter_by(key=key).first()
    if template is not None:
        return list(template.available_variables or [])
    fallback = _seed_available_variables(key)
    if fallback:
        return fallback
    raise EmailTemplateNotFound(f"Email template '{key}' is not seeded.")


def validate_context(key: str, context: dict) -> list[str]:
    required = available_variables_for(key)
    missing: list[str] = []
    for var in required:
        if var not in context or context[var] is None:
            missing.append(var)
    return missing


def render_strings(
    *,
    subject: str,
    body_text: str,
    body_html: Optional[str],
    context: Mapping[str, Any],
) -> RenderedEmail:
    merged: dict[str, Any] = {"from_name": _from_name()}
    merged.update(dict(context))

    rendered_subject = _render(subject, merged, html=False).strip()
    rendered_text = _render(body_text, merged, html=False)
    rendered_html = _render(body_html, merged, html=True) if body_html else None
    return RenderedEmail(subject=rendered_subject, html=rendered_html, text=rendered_text)


def render_template_for(key: str, context: dict) -> RenderedEmail:
    template = _lookup_template(key)
    return render_strings(
        subject=template.subject,
        body_text=template.body_text,
        body_html=template.body_html,
        context=context,
    )
