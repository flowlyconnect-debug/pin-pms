"""Spec section 16 — käyttäjän luonti."""
from __future__ import annotations


def test_create_user_via_cli(app):
    """``flask create-user`` persists a fresh user with the chosen role.

    Uses Flask's CLI runner so we exercise the same code path the customer
    operates in production. All option values are passed on the command line
    to bypass the interactive ``prompt=True`` Click decorators.
    """

    from app.users.models import User

    runner = app.test_cli_runner()
    result = runner.invoke(
        args=[
            "create-user",
            "--email",
            "newbie@test.local",
            "--password",
            "Password123!",
            "--role",
            "user",
            "--organization-name",
            "Test Org For CLI",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Created user" in result.output

    created = User.query.filter_by(email="newbie@test.local").first()
    assert created is not None
    assert created.role == "user"
    assert created.is_active is True
    # The CLI hashes the password — never store the plaintext.
    assert created.password_hash != "Password123!"
    assert created.check_password("Password123!") is True
