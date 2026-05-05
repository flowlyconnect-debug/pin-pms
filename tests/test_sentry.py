from __future__ import annotations

import sys
from types import SimpleNamespace

from app import init_sentry
from app.cli import _safe_sentry_project_url


def test_sentry_init_skips_when_dsn_missing(app, monkeypatch):
    called = {"init": 0}
    fake_sdk = SimpleNamespace(init=lambda **kwargs: called.__setitem__("init", called["init"] + 1))
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
    monkeypatch.setitem(
        sys.modules,
        "sentry_sdk.integrations.flask",
        SimpleNamespace(FlaskIntegration=lambda: object()),
    )
    monkeypatch.setitem(
        sys.modules,
        "sentry_sdk.integrations.sqlalchemy",
        SimpleNamespace(SqlalchemyIntegration=lambda: object()),
    )
    app.config["SENTRY_DSN"] = ""
    init_sentry(app)
    assert called["init"] == 0


def test_sentry_redact_strips_secrets():
    from app import _redact_sentry_event

    event = {
        "request": {
            "headers": {"Authorization": "Bearer abc"},
            "data": {"email": "x@example.com", "password": "secret"},
        },
        "extra": {
            "password": "pw",
            "token": "tok",
            "api_key": "key",
            "secret": "secret-value",
            "nested": {"api-key": "abc"},
        },
    }
    redacted = _redact_sentry_event(event, None)
    assert redacted["extra"]["password"] == "***"
    assert redacted["extra"]["token"] == "***"
    assert redacted["extra"]["api_key"] == "***"
    assert redacted["extra"]["secret"] == "***"
    assert redacted["extra"]["nested"]["api-key"] == "***"


def test_sentry_redact_strips_authorization_header():
    from app import _redact_sentry_event

    event = {
        "request": {
            "headers": {
                "Authorization": "Bearer token",
                "Cookie": "session=abc",
                "X-API-Key": "key-123",
            }
        }
    }
    redacted = _redact_sentry_event(event, None)
    headers = redacted["request"]["headers"]
    assert headers["Authorization"] == "***"
    assert headers["Cookie"] == "***"
    assert headers["X-API-Key"] == "***"


def test_sentry_redact_strips_request_data():
    from app import _redact_sentry_event

    event = {"request": {"data": {"ssn": "123-45-6789", "email": "test@example.com"}}}
    redacted = _redact_sentry_event(event, None)
    assert redacted["request"]["data"] == "[redacted]"


def test_sentry_test_cli_command(app, monkeypatch):
    messages: list[str] = []
    fake_sdk = SimpleNamespace(capture_message=lambda msg: messages.append(msg))
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
    dsn = "https://public-secret@example.ingest.sentry.io/12345"
    app.config["SENTRY_DSN"] = dsn
    runner = app.test_cli_runner()
    result = runner.invoke(args=["sentry-test"])
    assert result.exit_code == 0, result.output
    assert messages == ["Sentry test from Pin PMS CLI"]
    assert "public-secret@" not in result.output
    assert dsn not in result.output
    assert _safe_sentry_project_url(dsn) in result.output
