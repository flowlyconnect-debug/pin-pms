from __future__ import annotations

import io
import logging

import pytest

from app.core.logging import RedactingFilter, redact

pytestmark = pytest.mark.no_db_isolation


@pytest.mark.parametrize(
    ("raw", "needle", "forbidden"),
    [
        ("password=secret123", "password=***", "secret123"),
        ("token=abc123", "token=***", "abc123"),
        ("api_key=abc123", "api_key=***", "abc123"),
        ("api-key=abc123", "api-key=***", "abc123"),
        ("secret=abc123", "secret=***", "abc123"),
        ("authorization=Bearer abc123", "authorization=***", "abc123"),
        ("x-api-key=abc123", "x-api-key=***", "abc123"),
    ],
)
def test_redact_masks_sensitive_pairs(raw: str, needle: str, forbidden: str) -> None:
    out = redact(raw)
    assert needle in out
    assert forbidden not in out


def test_redacting_filter_masks_logger_message() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter())
    log = logging.getLogger("pindora.test_logging_redacting")
    log.handlers.clear()
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    log.info("password=secret123")
    body = stream.getvalue()
    assert "password=***" in body
    assert "secret123" not in body


def test_create_app_production_requires_env_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MAILGUN_API_KEY", raising=False)
    from app import create_app

    with pytest.raises(RuntimeError, match="Missing required environment variable"):
        create_app("production")
