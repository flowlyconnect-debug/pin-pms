"""Spec section 5 — varakoodit palautustilanteita varten."""
from __future__ import annotations


def test_generate_backup_codes_persists_only_hashes(superadmin):
    from app.extensions import db
    from app.users.models import User

    plaintext = superadmin.generate_backup_codes()
    db.session.commit()

    refreshed = User.query.get(superadmin.id)

    assert len(plaintext) == 10
    assert len(refreshed.backup_codes) == 10
    # Stored entries are SHA-256 hex digests, not the raw codes.
    for raw_code, stored_hash in zip(plaintext, refreshed.backup_codes):
        assert raw_code != stored_hash
        assert len(stored_hash) == 64  # SHA-256 hex


def test_consume_backup_code_is_one_time(superadmin):
    from app.extensions import db

    plaintext = superadmin.generate_backup_codes()
    db.session.commit()

    code = plaintext[0]
    assert superadmin.consume_backup_code(code) is True
    db.session.commit()

    # Second use must fail.
    assert superadmin.consume_backup_code(code) is False
    assert superadmin.backup_codes_remaining == 9


def test_2fa_verify_accepts_backup_code(client, superadmin):
    """A backup code stands in for a TOTP code at /2fa/verify."""

    from app.extensions import db

    plaintext = superadmin.generate_backup_codes()
    db.session.commit()

    # Log in first.
    client.post(
        "/login",
        data={"email": superadmin.email, "password": superadmin.password_plain},
    )
    response = client.post(
        "/2fa/verify",
        data={"code": plaintext[0]},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/admin" in response.headers["Location"]

    # The code is consumed.
    db.session.refresh(superadmin)
    assert superadmin.backup_codes_remaining == 9
