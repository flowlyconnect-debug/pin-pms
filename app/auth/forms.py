from dataclasses import dataclass

from flask import Request


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
