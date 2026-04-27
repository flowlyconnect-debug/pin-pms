"""Logging configuration — project brief section 1 + section 10.

Provides ``configure_logging(app)`` which sets up a structured stdout
formatter so journald / Docker logs are easy to grep. Logs intentionally
omit any field that could contain a password, token, or API key — see
the :func:`SecretRedactingFilter` filter below.
"""
from __future__ import annotations

import logging
import re
from logging import Formatter, LogRecord, StreamHandler

from flask import Flask


# Pattern matches inline secrets in log messages ("password=foo",
# "Authorization: Bearer abc...", "api_key=...") so a stray ``logger.info``
# cannot accidentally leak a credential into the log stream.
_SECRET_PATTERNS = [
    re.compile(r"(password\s*[:=]\s*)([^\s,;]+)", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[:=]\s*)([^\s,;]+)", re.IGNORECASE),
    re.compile(r"(authorization\s*:\s*bearer\s+)([^\s,;]+)", re.IGNORECASE),
    re.compile(r"(x-api-key\s*:\s*)([^\s,;]+)", re.IGNORECASE),
    re.compile(r"(secret\s*[:=]\s*)([^\s,;]+)", re.IGNORECASE),
]


class SecretRedactingFilter(logging.Filter):
    """Redact common credential patterns from formatted log records."""

    def filter(self, record: LogRecord) -> bool:  # noqa: D401 — logging API
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — never break logging
            return True
        redacted = message
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub(r"\1<redacted>", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(app: Flask) -> None:
    """Attach a stdout handler with the redaction filter and a sane format."""

    level_name = (app.config.get("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Pytest closes captured stdio during teardown; a StreamHandler on stderr
    # then raises "I/O operation on closed file" if background work still logs.
    if app.config.get("TESTING"):
        logging.raiseExceptions = False
        for existing in list(root.handlers):
            if getattr(existing, "_pindora_configured", False):
                root.removeHandler(existing)
        return

    # Avoid double-handlers when the dev auto-reloader respawns the app.
    if any(getattr(h, "_pindora_configured", False) for h in root.handlers):
        return

    handler = StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(
        Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    )
    handler.addFilter(SecretRedactingFilter())
    handler._pindora_configured = True  # type: ignore[attr-defined]
    root.addHandler(handler)
