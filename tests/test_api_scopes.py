from __future__ import annotations


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
