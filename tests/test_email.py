"""Spec section 16 — sähköpostipohjan renderöinti."""

from __future__ import annotations


def test_render_strings_substitutes_variables(app):
    """``render_strings`` performs straight Jinja substitution on all three slots."""

    from app.email.templates import render_strings

    rendered = render_strings(
        subject="Welcome {{ name }}",
        body_text="Hello {{ name }}, your code is {{ code }}.",
        body_html="<p>Hello <strong>{{ name }}</strong>, code: {{ code }}</p>",
        context={"name": "Alice", "code": "12345"},
    )

    assert rendered.subject == "Welcome Alice"
    assert rendered.text == "Hello Alice, your code is 12345."
    assert "Hello <strong>Alice</strong>" in (rendered.html or "")
    assert "12345" in (rendered.html or "")


def test_render_strings_html_autoescapes_but_text_does_not(app):
    """The HTML environment escapes; the plain-text environment passes through.

    Mailgun sends both bodies verbatim; the autoescape rule means a malicious
    or sloppy variable cannot inject markup into the HTML part, while the
    plain-text part stays exact for readers using a text-only client.
    """

    from app.email.templates import render_strings

    rendered = render_strings(
        subject="x",
        body_text="value: {{ value }}",
        body_html="<p>value: {{ value }}</p>",
        context={"value": "<script>alert(1)</script>"},
    )

    # Plain-text body keeps the raw characters — no HTML escaping there.
    assert "<script>alert(1)</script>" in rendered.text

    # HTML body must escape the angle brackets.
    assert "<script>" not in (rendered.html or "")
    assert "&lt;script&gt;" in (rendered.html or "")


def test_render_template_reads_seeded_db_row(app):
    """``render_template`` looks up the row by key and renders it.

    Seeds the table with one of the known template keys so we exercise the DB
    lookup path, not just the in-memory string renderer above.
    """

    from app.email.models import EmailTemplate, TemplateKey
    from app.email.templates import render_template_for
    from app.extensions import db

    db.session.add(
        EmailTemplate(
            key=TemplateKey.WELCOME_EMAIL,
            subject="Welcome to {{ organization_name }}",
            body_text="Hi {{ user_email }}",
            body_html=None,
            description="seed for test",
            available_variables=["user_email", "organization_name"],
        )
    )
    db.session.commit()

    rendered = render_template_for(
        TemplateKey.WELCOME_EMAIL,
        context={"user_email": "alice@example.com", "organization_name": "Pindora"},
    )

    assert rendered.subject == "Welcome to Pindora"
    assert rendered.text == "Hi alice@example.com"
    assert rendered.html is None
