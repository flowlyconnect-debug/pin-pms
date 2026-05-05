from __future__ import annotations

import logging
import re
from logging import LogRecord, StreamHandler
from typing import Any, Mapping, Sequence

import structlog
from flask import Flask, g, has_request_context, request
from flask_login import current_user

# Log message redaction: key=value, key: value, and Authorization Bearer …
# (?<![\w]) avoids matching e.g. ``secret`` inside unrelated identifiers.
_PAIR_KEYS = r"(?:password|token|api[_-]?key|secret|x-api-key|signature)"
_PAIR_RE = re.compile(
    rf"(?i)(?<![\w])(?P<key>{_PAIR_KEYS})\s*[:=]\s*(?P<val>[^\s,;]+)",
    re.IGNORECASE,
)
_AUTH_RE = re.compile(
    r"(?i)(?<![\w])(?P<key>authorization)\s*[:=]\s*(?:Bearer\s+)?(?P<val>[^\s,;]+)",
    re.IGNORECASE,
)

_SECRET_KEYS = {
    "password",
    "api_key",
    "authorization",
    "x_api_key",
    "token",
    "secret",
}


def redact(message: str) -> str:
    """Mask sensitive ``key=value`` / ``key: value`` fragments in a log line."""

    out = _PAIR_RE.sub(lambda m: f"{m.group('key')}=***", message)
    out = _AUTH_RE.sub(lambda m: f"{m.group('key')}=***", out)
    return out


class RedactingFilter(logging.Filter):
    """Strip secrets from log ``record.msg`` / ``record.args`` before formatting."""

    def filter(self, record: LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        record.__dict__ = _redact_secret_context(record.__dict__)
        return True


# Backwards-compatible name
SecretRedactingFilter = RedactingFilter


def _redact_secret_context(payload: Any) -> Any:
    if isinstance(payload, Mapping):
        is_secret = bool(payload.get("is_secret"))
        out: dict[Any, Any] = {}
        for key, value in payload.items():
            key_lower = str(key).lower()
            # Do not walk stdlib ``LogRecord.args`` as a generic sequence: it must
            # stay a tuple of the correct arity for %-format ``record.msg``.
            if key_lower == "args":
                out[key] = value
                continue
            if key_lower in _SECRET_KEYS:
                out[key] = "<redacted>"
                continue
            if is_secret and key_lower in {"value", "raw_value", "setting_value"}:
                out[key] = "***"
                continue
            out[key] = _redact_secret_context(value)
        return out
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [_redact_secret_context(item) for item in payload]
    if isinstance(payload, str):
        return redact(payload)
    return payload


def _attach_request_context(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    if not has_request_context():
        event_dict.setdefault("request_id", None)
        event_dict.setdefault("user_id", None)
        event_dict.setdefault("organization_id", None)
        event_dict.setdefault("route", None)
        return event_dict
    event_dict.setdefault("request_id", getattr(g, "request_id", None))
    user_id = None
    organization_id = getattr(g, "organization_id", None)
    try:
        if getattr(current_user, "is_authenticated", False):
            user_id = getattr(current_user, "id", None)
            if organization_id is None:
                organization_id = getattr(current_user, "organization_id", None)
    except Exception:
        pass
    event_dict.setdefault("user_id", user_id)
    event_dict.setdefault("organization_id", organization_id)
    event_dict.setdefault("route", request.path)
    return event_dict


def _normalize_for_json(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event = event_dict.pop("event", "")
    event_dict["message"] = str(event)
    if "logger" not in event_dict and "logger_name" in event_dict:
        event_dict["logger"] = event_dict.pop("logger_name")
    event_dict["extra"] = _redact_secret_context(
        {
            key: value
            for key, value in event_dict.items()
            if key
            not in {
                "timestamp",
                "level",
                "logger",
                "message",
                "request_id",
                "user_id",
                "organization_id",
                "route",
            }
        }
    )
    return _redact_secret_context(event_dict)


def configure_logging(app: Flask) -> None:
    level_name = (app.config.get("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    for existing in list(root.handlers):
        if getattr(existing, "_pindora_configured", False):
            root.removeHandler(existing)

    handler = StreamHandler()
    handler.setLevel(level)
    handler.addFilter(RedactingFilter())
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
                _attach_request_context,
                _normalize_for_json,
            ],
        )
    )
    handler._pindora_configured = True  # type: ignore[attr-defined]
    root.addHandler(handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
            _attach_request_context,
            _normalize_for_json,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def record_slow_query_observation(*, app: Flask, duration_ms: int, threshold_ms: int) -> None:
    try:
        import sentry_sdk
    except Exception:
        return
    sentry_sdk.add_breadcrumb(
        category="sql.slow_query",
        message="Slow SQL query",
        level="warning",
        data={"duration_ms": int(duration_ms), "threshold_ms": int(threshold_ms)},
    )
    if not has_request_context():
        return
    slow_query_count = int(getattr(g, "_slow_query_count", 0)) + 1
    g._slow_query_count = slow_query_count
    if slow_query_count == 6:
        sentry_sdk.capture_message("More than 5 slow queries in one request", level="warning")
        app.logger.warning(
            "slow_query_burst_detected",
            extra={"slow_query_count": slow_query_count, "threshold_ms": int(threshold_ms)},
        )
