"""Idempotency key behaviour for duplicate-safe POST handlers."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from app.api.schemas import json_error, json_ok


def _body_hash(payload: dict) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _register_counter_route(app, path: str, *, with_api_key: bool = False):
    """Register a POST route with ``@idempotent_post``; return mutable ``state``."""

    from app.api.auth import require_api_key
    from app.idempotency.decorators import idempotent_post

    state: dict = {"hits": 0, "kind": "ok"}

    def _inner():
        state["hits"] += 1
        kind = state.get("kind", "ok")
        if kind == "500":
            return json_error("server_error", "fail", status=500)
        if kind == "400":
            return json_error("bad_request", "bad", status=400)
        if kind == "422":
            return json_error("validation_error", "invalid", status=422)
        return json_ok({"hits": state["hits"]})

    endpoint = f"idem_{id(state)}"
    wrapped = idempotent_post(f"POST {path}")(_inner)
    if with_api_key:
        wrapped = require_api_key(wrapped)
    # Flask 3 locks route registration after first request. Test suite reuses
    # one app instance, so explicitly reopen setup for these ephemeral routes.
    app._got_first_request = False  # type: ignore[attr-defined]
    app.add_url_rule(path, endpoint=endpoint, view_func=wrapped, methods=["POST"])
    return state


@pytest.fixture
def idem_path(request) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", request.node.name).strip("_")
    return f"/api/v1/_idem_{slug}"


def test_idempotency_key_blocks_duplicate_request(app, client, idem_path):
    state = _register_counter_route(app, idem_path)
    headers = {"Content-Type": "application/json", "Idempotency-Key": "dup-key-1"}
    body = json.dumps({"a": 1})

    r1 = client.post(idem_path, data=body, headers=headers)
    r2 = client.post(idem_path, data=body, headers=headers)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert state["hits"] == 1
    assert r1.get_json() == r2.get_json()


def test_idempotency_key_conflict_on_different_payload(app, client, idem_path):
    _register_counter_route(app, idem_path)
    headers = {"Content-Type": "application/json", "Idempotency-Key": "conflict-key"}

    client.post(idem_path, data=json.dumps({"x": 1}), headers=headers)
    r2 = client.post(idem_path, data=json.dumps({"x": 2}), headers=headers)

    assert r2.status_code == 409
    data = r2.get_json()
    assert data["success"] is False
    assert data["error"]["code"] == "idempotency_key_conflict"


def test_missing_idempotency_key_returns_400(app, client, idem_path):
    _register_counter_route(app, idem_path)
    r = client.post(idem_path, data=json.dumps({}), headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    data = r.get_json()
    assert data["success"] is False
    assert data["error"]["code"] == "idempotency_key_required"


def test_expired_idempotency_key_allows_new_request(app, client, idem_path):
    from app.extensions import db
    from app.idempotency.models import IdempotencyKey

    _register_counter_route(app, idem_path)
    payload = {"renew": True}
    rh = _body_hash(payload)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    row = IdempotencyKey(
        key="expired-key",
        endpoint=f"POST {idem_path}",
        request_hash=rh,
        organization_id=None,
        created_at=past,
        expires_at=past,
    )
    db.session.add(row)
    db.session.commit()

    headers = {"Content-Type": "application/json", "Idempotency-Key": "expired-key"}
    r = client.post(idem_path, data=json.dumps(payload), headers=headers)
    assert r.status_code == 200
    assert r.get_json()["data"]["hits"] == 1


def test_prune_removes_expired_rows(app, organization):
    from app.extensions import db
    from app.idempotency.models import IdempotencyKey
    from app.idempotency.services import prune_expired

    now = datetime.now(timezone.utc)
    past = now - timedelta(days=2)
    future = now + timedelta(days=1)

    expired = IdempotencyKey(
        key="prune-old",
        endpoint="POST /api/v1/x",
        request_hash="0" * 64,
        organization_id=organization.id,
        created_at=past,
        expires_at=past,
    )
    valid = IdempotencyKey(
        key="prune-new",
        endpoint="POST /api/v1/x",
        request_hash="1" * 64,
        organization_id=organization.id,
        created_at=now,
        expires_at=future,
    )
    db.session.add_all([expired, valid])
    db.session.commit()

    n = prune_expired()
    assert n == 1
    assert IdempotencyKey.query.filter_by(key="prune-old").first() is None
    assert IdempotencyKey.query.filter_by(key="prune-new").first() is not None


def test_idempotency_audit_log_created(app, client, idem_path):
    from app.audit.models import AuditLog

    _register_counter_route(app, idem_path)
    headers = {"Content-Type": "application/json", "Idempotency-Key": "audit-key"}
    body = json.dumps({"z": 1})

    client.post(idem_path, data=body, headers=headers)
    client.post(idem_path, data=body, headers=headers)

    replay = (
        AuditLog.query.filter_by(action="idempotency.replay").order_by(AuditLog.id.desc()).first()
    )
    assert replay is not None
    assert replay.target_type == "idempotency_key"
    assert replay.context.get("endpoint") == f"POST {idem_path}"

    client.post(idem_path, data=json.dumps({"z": 2}), headers=headers)
    conflict = (
        AuditLog.query.filter_by(action="idempotency.conflict").order_by(AuditLog.id.desc()).first()
    )
    assert conflict is not None
    assert conflict.target_type == "idempotency_key"
    assert conflict.context.get("status") == "failure"


def test_cached_5xx_is_not_stored(app, client, idem_path):
    state = _register_counter_route(app, idem_path)
    state["kind"] = "500"
    headers = {"Content-Type": "application/json", "Idempotency-Key": "five-key"}
    body = json.dumps({})

    r1 = client.post(idem_path, data=body, headers=headers)
    r2 = client.post(idem_path, data=body, headers=headers)

    assert r1.status_code == 500
    assert r2.status_code == 500
    assert state["hits"] == 2


def test_cached_4xx_except_422_is_not_stored(app, client, idem_path):
    state = _register_counter_route(app, idem_path)
    headers = {"Content-Type": "application/json", "Idempotency-Key": "four-key"}
    body = json.dumps({})

    state["kind"] = "400"
    client.post(idem_path, data=body, headers=headers)
    client.post(idem_path, data=body, headers=headers)
    assert state["hits"] == 2

    state["hits"] = 0
    state["kind"] = "422"
    r1 = client.post(idem_path, data=body, headers=headers)
    client.post(idem_path, data=body, headers=headers)
    assert r1.status_code == 422
    assert state["hits"] == 1


def test_organization_id_saved_when_available(app, client, idem_path, api_key):
    _register_counter_route(app, idem_path, with_api_key=True)
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": "org-key",
        "X-API-Key": api_key.raw,
    }
    client.post(idem_path, data=json.dumps({}), headers=headers)

    from app.idempotency.models import IdempotencyKey

    row = IdempotencyKey.query.filter_by(key="org-key").one()
    assert row.organization_id == api_key.organization_id


def test_x_idempotency_key_header_accepted(app, client, idem_path):
    state = _register_counter_route(app, idem_path)
    headers = {"Content-Type": "application/json", "X-Idempotency-Key": "x-key"}
    body = json.dumps({"n": 1})
    client.post(idem_path, data=body, headers=headers)
    client.post(idem_path, data=body, headers=headers)
    assert state["hits"] == 1
