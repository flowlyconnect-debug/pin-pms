from __future__ import annotations

import pytest

from app.auth.forms import ResetPasswordForm
from app.core.security import validate_password_strength
from app.users import services as user_services
from app.users.models import UserRole


def test_validate_password_strength_enforces_length_letter_and_number(monkeypatch):
    monkeypatch.setenv("PASSWORD_MIN_LENGTH", "12")

    errors = validate_password_strength("abcdefghijk")
    assert "Password must be at least 12 characters long." in errors
    assert "Password must include at least one number." in errors

    errors = validate_password_strength("123456789012")
    assert "Password must include at least one letter." in errors

    assert validate_password_strength("StrongPass1234") == []


def test_reset_password_form_rejects_weak_password():
    form = ResetPasswordForm(password="alllettersonly", confirm="alllettersonly")
    ok, error = form.validate()
    assert ok is False
    assert error == "Password must include at least one number."


def test_create_user_rejects_weak_password(app, organization):
    with app.app_context():
        with pytest.raises(
            user_services.UserServiceError,
            match="at least one number",
        ):
            user_services.create_user(
                email="weak@test.local",
                password="onlyletterspassword",
                role=UserRole.USER.value,
                organization_id=organization.id,
            )


def test_change_password_rejects_weak_password(app, organization):
    with app.app_context():
        user = user_services.create_user(
            email="policy@test.local",
            password="StrongPass1234",
            role=UserRole.USER.value,
            organization_id=organization.id,
        )

        with pytest.raises(
            user_services.UserServiceError,
            match="at least one letter",
        ):
            user_services.change_password(
                user_id=user.id,
                new_password="123456789012",
            )
