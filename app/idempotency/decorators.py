from __future__ import annotations

import hashlib
import json
import logging
from functools import wraps
from typing import Any, Callable

from flask import Response, has_request_context, request

from app.api.schemas import json_error
from app.audit import record as audit_record
from app.extensions import db
from app.idempotency.services import IdempotencyKeyConflict, get_or_create, record_response

logger = logging.getLogger(__name__)

_IDEMPOTENCY_HEADERS = ("Idempotency-Key", "X-Idempotency-Key")


def _read_idempotency_key() -> str | None:
    if not has_request_context():
        return None
    for name in _IDEMPOTENCY_HEADERS:
        raw = (request.headers.get(name) or "").strip()
        if raw:
            return raw[:128]
    return None


def _request_body_hash() -> str:
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _unpack_view_return(rv: Any) -> tuple[int, Any, Response | None]:
    """Return ``(status, body_for_cache, response_or_none)``."""

    if isinstance(rv, tuple):
        resp = rv[0]
        status = int(rv[1]) if len(rv) > 1 else 200
    else:
        resp = rv
        status = 200

    if isinstance(resp, Response):
        return status, resp, resp
    return status, resp, None


def idempotent_post(endpoint_name: str) -> Callable:
    """Guard a POST view with idempotency semantics (headers + body hash).

    Apply *below* ``@require_api_key`` so authentication still runs before replay
    short-circuits the view.
    """

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapper(*args: Any, **kwargs: Any):
            key = _read_idempotency_key()
            if not key:
                return json_error(
                    "idempotency_key_required",
                    "Send 'Idempotency-Key: <unique-string>' header to safely retry POST requests.",
                    status=400,
                )

            request_hash = _request_body_hash()
            try:
                row, created = get_or_create(key, endpoint_name, request_hash)
            except IdempotencyKeyConflict:
                return json_error(
                    "idempotency_key_conflict",
                    "This idempotency key was already used with a different JSON body.",
                    status=409,
                )

            if not created:
                if row.response_status is not None and row.response_body is not None:
                    audit_record(
                        "idempotency.replay",
                        target_type="idempotency_key",
                        target_id=row.id,
                        metadata={"endpoint": endpoint_name},
                    )
                    return Response(
                        row.response_body,
                        status=int(row.response_status),
                        mimetype="application/json",
                    )
                return json_error(
                    "idempotency_request_in_progress",
                    "This idempotency key is already in use for an in-flight request; retry shortly.",
                    status=503,
                )

            try:
                rv = view_func(*args, **kwargs)
            except Exception:
                db.session.rollback()
                raise

            status, body_for_cache, response_obj = _unpack_view_return(rv)
            try:
                record_response(row, status, body_for_cache)
            except Exception:  # noqa: BLE001 — caching must not break the handler.
                logger.exception("record_response failed for idempotency_key id=%s", row.id)

            return rv

        return wrapper

    return decorator
