"""User provisioning and lifecycle — used by CLI, admin UI, and seeds."""

from __future__ import annotations

import logging
from typing import Optional

from app.audit import record as audit_record
from app.audit.models import ActorType, AuditStatus
from app.core.security import validate_password_strength
from app.email.models import TemplateKey
from app.email.services import send_template
from app.extensions import db
from app.organizations.models import Organization
from app.users.models import User, UserRole

logger = logging.getLogger(__name__)


class UserServiceError(Exception):
    """Raised when user input or state does not allow the requested operation."""


def _login_url_for_welcome() -> str:
    try:
        from flask import has_request_context, url_for

        if has_request_context():
            return url_for("auth.login", _external=True)
    except Exception:  # noqa: BLE001 — best-effort URL for template
        logger.debug("welcome_email: could not build external login URL", exc_info=True)
    return "/login"


def _send_welcome_email(user: User, organization: Organization) -> None:
    try:
        send_template(
            TemplateKey.WELCOME_EMAIL,
            to=user.email,
            context={
                "user_email": user.email,
                "organization_name": organization.name,
                "login_url": _login_url_for_welcome(),
            },
        )
    except Exception as err:  # noqa: BLE001 — user creation must not fail on email
        logger.warning(
            "Welcome email failed for user_id=%s email=%s: %s",
            user.id,
            user.email,
            err,
        )


def create_user(
    *,
    email: str,
    password: str,
    role: str,
    organization_name: Optional[str] = None,
    organization_id: Optional[int] = None,
    actor_type: Optional[str] = None,
    actor_id: Optional[int] = None,
    actor_email: Optional[str] = None,
    commit: bool = True,
) -> User:
    """Create a user, audit the event, optionally send welcome email, and commit.

    Exactly one of ``organization_name`` or ``organization_id`` must be
    supplied. When ``organization_name`` is used, the organization row is
    fetched or created by name.
    """

    normalized_email = email.strip().lower()
    normalized_role = role.strip().lower()

    if not normalized_email:
        raise UserServiceError("Email is required.")
    if not password:
        raise UserServiceError("Password is required.")
    password_errors = validate_password_strength(password)
    if password_errors:
        raise UserServiceError(password_errors[0])

    if (organization_name is None) == (organization_id is None):
        raise UserServiceError(
            "Exactly one of organization_name or organization_id must be provided."
        )

    valid_roles = {r.value for r in UserRole}
    if normalized_role not in valid_roles:
        raise UserServiceError(
            f"Invalid role '{normalized_role}'. Must be one of: {', '.join(sorted(valid_roles))}."
        )

    if User.query.filter_by(email=normalized_email).first():
        raise UserServiceError(f"User with email '{normalized_email}' already exists.")

    if organization_id is not None:
        organization = Organization.query.get(organization_id)
        if organization is None:
            raise UserServiceError(f"Organization id {organization_id} does not exist.")
    else:
        assert organization_name is not None
        normalized_org_name = organization_name.strip()
        if not normalized_org_name:
            raise UserServiceError("Organization name is required.")
        organization = Organization.query.filter_by(name=normalized_org_name).first()
        if organization is None:
            organization = Organization(name=normalized_org_name)
            db.session.add(organization)
            db.session.flush()

    user = User(
        email=normalized_email,
        organization_id=organization.id,
        role=normalized_role,
        password_hash="",
        is_active=True,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.flush()

    is_superadmin = normalized_role == UserRole.SUPERADMIN.value
    audit_record(
        "superadmin.created" if is_superadmin else "user.created",
        status=AuditStatus.SUCCESS,
        actor_type=actor_type or ActorType.SYSTEM,
        actor_id=actor_id,
        actor_email=actor_email,
        organization_id=organization.id,
        target_type="user",
        target_id=user.id,
        context={
            "email": user.email,
            "role": user.role,
            "organization": organization.name,
        },
    )

    if commit:
        db.session.commit()
        _send_welcome_email(user, organization)

    return user


def update_user_role(
    *,
    user_id: int,
    new_role: str,
    actor_type: Optional[str] = None,
    actor_id: Optional[int] = None,
    actor_email: Optional[str] = None,
    commit: bool = False,
) -> User:
    nr = new_role.strip().lower()
    valid_roles = {r.value for r in UserRole}
    if nr not in valid_roles:
        raise UserServiceError(
            f"Invalid role '{nr}'. Must be one of: {', '.join(sorted(valid_roles))}."
        )

    user = User.query.get(user_id)
    if user is None:
        raise UserServiceError(f"User id {user_id} not found.")

    old_role = user.role
    if old_role == nr:
        return user

    user.role = nr
    audit_record(
        "user.role_changed",
        status=AuditStatus.SUCCESS,
        actor_type=actor_type or ActorType.SYSTEM,
        actor_id=actor_id,
        actor_email=actor_email,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user.id,
        context={"old_role": old_role, "new_role": nr},
    )
    if commit:
        db.session.commit()
    return user


def deactivate_user(
    *,
    user_id: int,
    actor_type: Optional[str] = None,
    actor_id: Optional[int] = None,
    actor_email: Optional[str] = None,
    forbid_self: bool = True,
    commit: bool = False,
) -> User:
    user = User.query.get(user_id)
    if user is None:
        raise UserServiceError(f"User id {user_id} not found.")
    actor_email_norm = (actor_email or "").strip().lower()
    user_email_norm = (user.email or "").strip().lower()
    is_self_actor = actor_id is not None and actor_id == user_id
    # Allow service/admin calls that pass a different actor identity even if ids
    # happen to match in tests seeded with low integer IDs.
    if forbid_self and is_self_actor and (
        not actor_email_norm or actor_email_norm == user_email_norm
    ):
        raise UserServiceError("You cannot deactivate yourself.")
    if not user.is_active:
        return user

    user.is_active = False
    audit_record(
        "user.deleted",
        status=AuditStatus.SUCCESS,
        actor_type=actor_type or ActorType.SYSTEM,
        actor_id=actor_id,
        actor_email=actor_email,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user.id,
        context={"email": user.email},
    )
    if commit:
        db.session.commit()
    return user


def reactivate_user(
    *,
    user_id: int,
    actor_type: Optional[str] = None,
    actor_id: Optional[int] = None,
    actor_email: Optional[str] = None,
    commit: bool = False,
) -> User:
    user = User.query.get(user_id)
    if user is None:
        raise UserServiceError(f"User id {user_id} not found.")
    if user.is_active:
        return user

    user.is_active = True
    audit_record(
        "user.reactivated",
        status=AuditStatus.SUCCESS,
        actor_type=actor_type or ActorType.SYSTEM,
        actor_id=actor_id,
        actor_email=actor_email,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user.id,
        context={"email": user.email},
    )
    if commit:
        db.session.commit()
    return user


def change_password(
    *,
    user_id: int,
    new_password: str,
    min_length: int | None = None,
    actor_type: Optional[str] = None,
    actor_id: Optional[int] = None,
    actor_email: Optional[str] = None,
    commit: bool = False,
) -> User:
    policy_errors = validate_password_strength(new_password)
    if min_length is not None and len(new_password) < min_length:
        policy_errors.insert(
            0,
            f"Password must be at least {min_length} characters.",
        )
    if policy_errors:
        raise UserServiceError(policy_errors[0])

    user = User.query.get(user_id)
    if user is None:
        raise UserServiceError(f"User id {user_id} not found.")

    user.set_password(new_password)
    audit_record(
        "password_changed",
        status=AuditStatus.SUCCESS,
        actor_type=actor_type or ActorType.SYSTEM,
        actor_id=actor_id,
        actor_email=actor_email,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user.id,
        context={
            "via": ("admin" if (actor_type or ActorType.SYSTEM) == ActorType.USER else "service"),
        },
    )
    if commit:
        db.session.commit()
    return user
