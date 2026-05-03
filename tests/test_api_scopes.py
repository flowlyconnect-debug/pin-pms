from __future__ import annotations

import pytest


def _auth_headers(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


def test_reservations_read_scope_cannot_create(client, regular_user):
    from app.api.models import ApiKey
    from app.extensions import db
    from app.properties.models import Property, Unit

    key, raw = ApiKey.issue(
        name="Reservations read only",
        organization_id=regular_user.organization_id,
        user_id=regular_user.id,
        scopes="reservations:read",
    )
    db.session.add(key)
    db.session.flush()

    prop = Property(organization_id=regular_user.organization_id, name="Scope hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.commit()

    response = client.post(
        "/api/v1/reservations",
        json={
            "unit_id": unit.id,
            "guest_id": regular_user.id,
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
        },
        headers=_auth_headers(raw),
    )
    assert response.status_code == 403
    payload = response.get_json()
    assert payload["error"]["code"] == "forbidden"
    assert "reservations:write" in payload["error"]["message"]


def test_health_and_me_skip_global_scope_hook(client, api_key):
    r_health = client.get("/api/v1/health")
    assert r_health.status_code == 200
    assert r_health.get_json()["success"] is True

    r_me = client.get("/api/v1/me", headers=_auth_headers(api_key.raw))
    assert r_me.status_code == 200
    assert r_me.get_json()["success"] is True


def test_api_key_without_scopes_gets_403_on_scoped_route(client, regular_user):
    from app.api.models import ApiKey
    from app.extensions import db

    key, raw = ApiKey.issue(
        name="Empty scopes",
        organization_id=regular_user.organization_id,
        user_id=regular_user.id,
        scopes="",
    )
    db.session.add(key)
    db.session.commit()

    r = client.get("/api/v1/properties?page=1&per_page=5", headers=_auth_headers(raw))
    assert r.status_code == 403
    body = r.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "forbidden"


@pytest.mark.parametrize(
    ("scopes", "path", "expected_status"),
    [
        ("", "/api/v1/properties?page=1&per_page=5", 403),
        ("reservations:read", "/api/v1/properties?page=1&per_page=5", 403),
        ("properties:read", "/api/v1/properties?page=1&per_page=5", 200),
        ("", "/api/v1/reservations?page=1&per_page=5", 403),
        ("properties:read", "/api/v1/reservations?page=1&per_page=5", 403),
        ("reservations:read", "/api/v1/reservations?page=1&per_page=5", 200),
        ("", "/api/v1/invoices?page=1&per_page=5", 403),
        ("properties:read", "/api/v1/invoices?page=1&per_page=5", 403),
        ("invoices:read", "/api/v1/invoices?page=1&per_page=5", 200),
        ("", "/api/v1/maintenance-requests?page=1&per_page=5", 403),
        ("invoices:read", "/api/v1/maintenance-requests?page=1&per_page=5", 403),
        ("maintenance:read", "/api/v1/maintenance-requests?page=1&per_page=5", 200),
        ("", "/api/v1/health/ready", 403),
        ("properties:read", "/api/v1/health/ready", 403),
        ("reports:read", "/api/v1/health/ready", 200),
        ("", "/api/v1/openapi.json", 403),
        ("properties:read", "/api/v1/openapi.json", 403),
        ("reports:read", "/api/v1/openapi.json", 200),
    ],
)
def test_scope_matrix_get_routes(client, regular_user, scopes: str, path: str, expected_status: int):
    from app.api.models import ApiKey
    from app.extensions import db

    key, raw = ApiKey.issue(
        name="matrix",
        organization_id=regular_user.organization_id,
        user_id=regular_user.id,
        scopes=scopes,
    )
    db.session.add(key)
    db.session.commit()

    response = client.get(path, headers=_auth_headers(raw))
    if "health/ready" in path and expected_status == 200:
        assert response.status_code in (200, 503), response.get_json()
    else:
        assert response.status_code == expected_status, response.get_json()


def test_properties_write_scope_for_create(client, regular_user):
    from app.api.models import ApiKey
    from app.extensions import db

    read_key, read_raw = ApiKey.issue(
        name="read",
        organization_id=regular_user.organization_id,
        user_id=regular_user.id,
        scopes="properties:read",
    )
    db.session.add(read_key)
    write_key, write_raw = ApiKey.issue(
        name="write",
        organization_id=regular_user.organization_id,
        user_id=regular_user.id,
        scopes="properties:write",
    )
    db.session.add(write_key)
    db.session.commit()

    denied = client.post(
        "/api/v1/properties",
        json={"name": "Denied prop", "address": "1"},
        headers=_auth_headers(read_raw),
    )
    assert denied.status_code == 403

    ok = client.post(
        "/api/v1/properties",
        json={"name": "Allowed prop", "address": "2"},
        headers=_auth_headers(write_raw),
    )
    assert ok.status_code == 201


def test_guard_returns_500_when_required_scope_attr_removed(app, client, api_key, monkeypatch):
    view_func = app.view_functions["api.list_properties"]
    monkeypatch.delattr(view_func, "_required_scope", raising=False)
    response = client.get("/api/v1/properties?page=1&per_page=5", headers=_auth_headers(api_key.raw))
    assert response.status_code == 500
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "internal_error"


def test_all_api_v1_routes_have_required_scope_or_are_whitelisted(app):
    whitelist = {"/api/v1/health", "/api/v1/me"}
    missing: list[str] = []

    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/v1/"):
            continue
        if rule.rule in whitelist:
            continue
        if rule.endpoint == "static":
            continue

        view_func = app.view_functions.get(rule.endpoint)
        if view_func is None:
            continue

        if not hasattr(view_func, "_required_scope"):
            missing.append(f"{rule.rule} ({rule.endpoint})")

    assert not missing, f"Missing @scope_required on: {missing}"
