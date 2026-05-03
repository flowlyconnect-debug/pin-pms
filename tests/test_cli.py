"""CLI command tests."""

from __future__ import annotations

from app.api.models import ApiKey
from app.audit.models import AuditLog
from app.extensions import db


def test_rotate_api_key_command(app, regular_user):
    from app.api.models import _hash_key

    key, _discarded_raw = ApiKey.issue(
        name="CLI rotate key",
        organization_id=regular_user.organization_id,
        user_id=regular_user.id,
        scopes="reservations:read,invoices:read",
    )
    db.session.add(key)
    db.session.commit()
    old_id = key.id
    count_before = ApiKey.query.count()

    runner = app.test_cli_runner()
    result = runner.invoke(
        args=[
            "rotate-api-key",
            "--key-id",
            str(old_id),
            "--reason",
            "test reason",
        ]
    )
    assert result.exit_code == 0, result.output

    lines = [ln for ln in result.output.strip().splitlines() if ln.strip()]
    assert len(lines) == 1, "plaintext key should be printed exactly once as a single line"
    new_raw = lines[0]
    assert new_raw.startswith("pms_")

    db.session.expire_all()
    old = db.session.get(ApiKey, old_id)
    assert old is not None
    assert old.is_active is False
    assert old.rotated_at is not None

    new_rows = [k for k in ApiKey.query.all() if k.id != old_id and k.is_active]
    assert len(new_rows) == 1
    new_key = new_rows[0]
    assert new_key.name == old.name
    assert new_key.scopes == old.scopes
    assert new_key.organization_id == old.organization_id
    assert new_key.expires_at == old.expires_at
    assert new_key.key_hash == _hash_key(new_raw)
    assert ApiKey.query.count() == count_before + 1

    assert old.key_hash not in result.output
    assert new_key.key_hash not in result.output

    for row in ApiKey.query.all():
        assert row.key_hash != new_raw
        assert row.name != new_raw
        assert row.key_prefix != new_raw

    audit = AuditLog.query.filter_by(action="api_key.rotated").order_by(AuditLog.id.desc()).first()
    assert audit is not None
    assert audit.target_type == "api_key"
    assert audit.target_id == old_id
    assert audit.context is not None
    assert audit.context.get("new_key_id") == new_key.id
    assert audit.context.get("reason") == "test reason"

    bogus = runner.invoke(args=["rotate-api-key", "--key-id", "999999999"])
    assert bogus.exit_code == 1
    assert bogus.output.strip()
    assert ApiKey.query.count() == count_before + 1
