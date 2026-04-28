from __future__ import annotations

from app.auth.models import LoginAttempt


def test_login_locks_out_after_too_many_failed_attempts(client, regular_user):
    for _ in range(6):
        resp = client.post(
            "/login",
            data={
                "email": regular_user.email,
                "password": "wrong-password",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200

    blocked = client.post(
        "/login",
        data={
            "email": regular_user.email,
            "password": regular_user.password_plain,
        },
        follow_redirects=False,
    )

    assert blocked.status_code == 200
    assert b"Invalid email or password" in blocked.data


def test_successful_login_resets_failed_attempt_counter(client, regular_user):
    for _ in range(5):
        resp = client.post(
            "/login",
            data={
                "email": regular_user.email,
                "password": "wrong-password",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200

    success = client.post(
        "/login",
        data={
            "email": regular_user.email,
            "password": regular_user.password_plain,
        },
        follow_redirects=False,
    )

    assert success.status_code == 302

    failed_count = LoginAttempt.query.filter_by(email=regular_user.email, success=False).count()
    success_count = LoginAttempt.query.filter_by(email=regular_user.email, success=True).count()
    assert failed_count == 0
    assert success_count >= 1
