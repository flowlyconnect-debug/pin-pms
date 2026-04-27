"""Spec section 4 — salasanan resetointi sähköpostilla."""
from __future__ import annotations


def test_forgot_password_emits_token_and_returns_neutral_response(client, regular_user):
    """POST /forgot-password issues a reset token without leaking existence."""

    from app.auth.models import PasswordResetToken
    from app.extensions import db

    response = client.post(
        "/forgot-password",
        data={"email": regular_user.email},
        follow_redirects=False,
    )
    # Always redirects to /login regardless of whether the address exists.
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    # A reset token was created in the DB.
    tokens = PasswordResetToken.query.filter_by(user_id=regular_user.id).all()
    assert len(tokens) == 1


def test_forgot_password_unknown_email_returns_same_response(client):
    response = client.post(
        "/forgot-password",
        data={"email": "ghost@nowhere.example"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_reset_password_consumes_token_and_changes_password(client, regular_user):
    from app.auth.models import PasswordResetToken
    from app.extensions import db

    row, raw = PasswordResetToken.issue(user_id=regular_user.id)
    db.session.add(row)
    db.session.commit()

    new_password = "BrandNewPass1234!"
    response = client.post(
        f"/reset-password/{raw}",
        data={"password": new_password, "confirm": new_password},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    db.session.refresh(row)
    assert row.used_at is not None

    # New password works, old one does not.
    db.session.refresh(regular_user)
    assert regular_user.check_password(new_password)
    assert not regular_user.check_password(regular_user.password_plain)


def test_reset_password_rejects_used_token(client, regular_user):
    from datetime import datetime, timezone
    from app.auth.models import PasswordResetToken
    from app.extensions import db

    row, raw = PasswordResetToken.issue(user_id=regular_user.id)
    row.used_at = datetime.now(timezone.utc)
    db.session.add(row)
    db.session.commit()

    response = client.get(f"/reset-password/{raw}")
    assert response.status_code == 200
    assert b"invalid" in response.data.lower()
