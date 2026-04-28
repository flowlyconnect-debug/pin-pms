from dataclasses import dataclass

from flask import Request

from app.core.security import validate_password_strength


@dataclass
class LoginForm:
    email: str
    password: str

    @classmethod
    def from_request(cls, request: Request) -> "LoginForm":
        payload = request.get_json(silent=True) or request.form
        return cls(
            email=(payload.get("email") or "").strip().lower(),
            password=payload.get("password") or "",
        )

    def validate(self) -> tuple[bool, str | None]:
        if not self.email:
            return False, "Email is required."
        if not self.password:
            return False, "Password is required."
        return True, None


@dataclass
class RegisterForm:
    email: str
    password: str
    confirm: str

    @classmethod
    def from_request(cls, request: Request) -> "RegisterForm":
        payload = request.get_json(silent=True) or request.form
        return cls(
            email=(payload.get("email") or "").strip().lower(),
            password=payload.get("password") or "",
            confirm=payload.get("confirm") or "",
        )

    def validate(self) -> tuple[bool, str | None]:
        if not self.email:
            return False, "Email is required."
        if not self.password:
            return False, "Password is required."
        errors = validate_password_strength(self.password)
        if errors:
            return False, errors[0]
        if self.password != self.confirm:
            return False, "Passwords do not match."
        return True, None


@dataclass
class ResetPasswordForm:
    password: str
    confirm: str

    @classmethod
    def from_request(cls, request: Request) -> "ResetPasswordForm":
        payload = request.get_json(silent=True) or request.form
        return cls(
            password=payload.get("password") or "",
            confirm=payload.get("confirm") or "",
        )

    def validate(self) -> tuple[bool, str | None]:
        errors = validate_password_strength(self.password)
        if errors:
            return False, errors[0]
        if self.password != self.confirm:
            return False, "Passwords do not match."
        return True, None
