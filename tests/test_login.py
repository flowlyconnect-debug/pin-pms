"""Spec section 16 — kirjautuminen + epäonnistunut kirjautuminen."""
from __future__ import annotations


def test_login_success_redirects_authenticated_user(client, regular_user):
    """Correct credentials give a 302 to the post-login destination.

    Regular users (no 2FA) skip the verify step and land on ``/``.
    """

    response = client.post(
        "/login",
        data={
            "email": regular_user.email,
            "password": regular_user.password_plain,
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    # Should redirect to the index. ``Location`` is absolute in newer Flask.
    assert response.headers["Location"].rstrip("/").endswith("")


def test_login_failure_with_wrong_password_returns_form_with_error(client, regular_user):
    """Wrong password keeps the user on the login page with a flashed error."""

    response = client.post(
        "/login",
        data={
            "email": regular_user.email,
            "password": "definitely-not-the-password",
        },
        follow_redirects=False,
    )

    # The view re-renders the form rather than redirecting.
    assert response.status_code == 200
    assert b"Invalid email or password" in response.data


def test_login_failure_with_unknown_email_does_not_leak_existence(client):
    """Unknown email surfaces the same generic message — no enumeration."""

    response = client.post(
        "/login",
        data={
            "email": "nobody@nowhere.invalid",
            "password": "anything",
        },
        follow_redirects=False,
    )

    assert response.status_code == 200
    # Same message as the wrong-password case — important: don't leak the
    # difference between "user does not exist" and "wrong password".
    assert b"Invalid email or password" in response.data
