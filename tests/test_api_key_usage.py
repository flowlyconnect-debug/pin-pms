from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyotp


def _auth_headers(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


def _login_superadmin(client, superadmin) -> None:
    client.post(
        "/login",
        data={"email": superadmin.email, "password": superadmin.password_plain},
    )
    code = pyotp.TOTP(superadmin.totp_secret).now()
    client.post("/2fa/verify", data={"code": code})


def test_require_api_key_updates_last_used_and_writes_usage_row(client, api_key):
    from app.api.models import ApiKey, ApiKeyUsage

    response = client.get("/api/v1/properties", headers=_auth_headers(api_key.raw))
    assert response.status_code == 200

    refreshed = ApiKey.query.get(api_key.id)
    assert refreshed.last_used_at is not None

    rows = ApiKeyUsage.query.filter_by(api_key_id=api_key.id).all()
    assert len(rows) == 1
    assert rows[0].endpoint == "/api/v1/properties"
    assert rows[0].status_code == 200


def test_invalid_api_key_does_not_write_usage_row(client):
    from app.api.models import ApiKeyUsage

    response = client.get("/api/v1/properties", headers=_auth_headers("pms_invalid"))
    assert response.status_code == 401
    assert ApiKeyUsage.query.count() == 0


def test_admin_api_key_usage_page_shows_latest_rows(client, superadmin, api_key):
    from app.api.models import ApiKeyUsage
    from app.extensions import db

    now = datetime.now(timezone.utc)
    for idx in range(105):
        db.session.add(
            ApiKeyUsage(
                api_key_id=api_key.id,
                endpoint=f"/api/v1/mock/{idx}",
                status_code=200,
                ip="127.0.0.1",
                user_agent="pytest",
                created_at=now + timedelta(seconds=idx),
            )
        )
    db.session.commit()

    _login_superadmin(client, superadmin)
    response = client.get(f"/admin/api-keys/{api_key.id}/usage")
    assert response.status_code == 200
    assert b"/api/v1/mock/104" in response.data
    assert b"/api/v1/mock/4" in response.data
    assert b"<code>/api/v1/mock/0</code>" not in response.data


def test_prune_api_key_usage_removes_old_rows(api_key):
    from app.api.models import ApiKeyUsage
    from app.api.services import prune_api_key_usage
    from app.extensions import db

    now = datetime.now(timezone.utc)
    old_row = ApiKeyUsage(
        api_key_id=api_key.id,
        endpoint="/api/v1/old",
        status_code=200,
        created_at=now - timedelta(days=91),
    )
    new_row = ApiKeyUsage(
        api_key_id=api_key.id,
        endpoint="/api/v1/new",
        status_code=200,
        created_at=now - timedelta(days=5),
    )
    db.session.add(old_row)
    db.session.add(new_row)
    db.session.commit()

    deleted = prune_api_key_usage(retention_days=90)
    assert deleted == 1
    assert ApiKeyUsage.query.filter_by(endpoint="/api/v1/old").first() is None
    assert ApiKeyUsage.query.filter_by(endpoint="/api/v1/new").first() is not None
