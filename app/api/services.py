from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.api.models import ApiKey, ApiKeyUsage
from app.audit import record as audit_record
from app.audit.models import ActorType, AuditStatus
from app.extensions import db
from app.properties.models import Property, Unit
from app.users.models import User


class ApiKeyRotateError(Exception):
    """Raised when an API key cannot be rotated (missing, inactive, etc.)."""


def rotate_api_key(key_id: int, *, reason: str | None = None) -> tuple[ApiKey, ApiKey, str]:
    """Rotate an API key by id.

    Deactivates the existing row (sets ``is_active`` and ``rotated_at``), inserts
    a replacement with the same name, scopes, organization, user, and expiry,
    and returns ``(old_key, new_key, plain_text_key)``.

    The plaintext value is never persisted — only ``new_key.key_hash`` is stored.
    """

    old = db.session.get(ApiKey, key_id)
    if old is None:
        raise ApiKeyRotateError(f"No API key found with id {key_id}.")
    if not old.is_active:
        raise ApiKeyRotateError(f"API key {key_id} is not active; cannot rotate.")

    new_key, raw_key = ApiKey.issue(
        name=old.name,
        organization_id=old.organization_id,
        user_id=old.user_id,
        scopes=old.scopes,
        expires_at=old.expires_at,
    )
    db.session.add(new_key)
    db.session.flush()

    old.is_active = False
    old.rotated_at = datetime.now(timezone.utc)

    audit_record(
        "api_key.rotated",
        status=AuditStatus.SUCCESS,
        organization_id=new_key.organization_id,
        target_type="api_key",
        target_id=old.id,
        context={
            "new_key_id": new_key.id,
            "prefix": new_key.key_prefix,
            "reason": (reason or "").strip(),
        },
        commit=False,
    )

    return old, new_key, raw_key


def audit_admin_api_key_created(*, api_key: ApiKey, actor_id: int, actor_email: str | None) -> None:
    audit_record(
        "apikey.created",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=actor_id,
        actor_email=actor_email,
        target_type="api_key",
        target_id=api_key.id,
        context={
            "name": api_key.name,
            "prefix": api_key.key_prefix,
            "scopes": api_key.scope_list,
        },
        commit=True,
    )


def audit_admin_api_key_toggle(*, api_key: ApiKey, actor_id: int, actor_email: str | None) -> None:
    audit_record(
        "apikey.active_toggled",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=actor_id,
        actor_email=actor_email,
        target_type="api_key",
        target_id=api_key.id,
        context={"is_active": api_key.is_active, "prefix": api_key.key_prefix},
        commit=True,
    )


def audit_admin_api_key_deleted(
    *, key_id: int, prefix: str, actor_id: int, actor_email: str | None
) -> None:
    audit_record(
        "apikey.deleted",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=actor_id,
        actor_email=actor_email,
        target_type="api_key",
        target_id=key_id,
        context={"prefix": prefix},
        commit=True,
    )


def record_api_key_usage(
    *,
    api_key_id: int,
    endpoint: str,
    status_code: int,
    ip: str | None,
    user_agent: str | None,
) -> None:
    row = ApiKeyUsage(
        api_key_id=api_key_id,
        endpoint=(endpoint or "")[:255] or "-",
        status_code=int(status_code),
        ip=(ip or None),
        user_agent=((user_agent or "")[:512] or None),
    )
    db.session.add(row)


class ApiKeyAdminError(Exception):
    """Business-rule failure when managing API keys from the admin UI."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def create_api_key_admin(
    *,
    name: str,
    organization_id: int,
    user_id: int | None,
    scopes: list[str],
    expires_at,
    actor_id: int,
    actor_email: str | None,
    actor_is_superadmin: bool,
) -> tuple[ApiKey, str]:
    """Validate input, persist a new API key, audit, and return ``(row, raw_key)``."""

    selected_scopes = list(scopes or [])
    if "admin:*" in selected_scopes and not actor_is_superadmin:
        raise ApiKeyAdminError("Vain pääylläpitäjä voi luoda API-avaimia admin:* -laajuudella.")

    if user_id is not None:
        selected_user = User.query.get(user_id)
        if selected_user is None:
            raise ApiKeyAdminError("Valittua käyttäjää ei ole olemassa.")
        if selected_user.organization_id != organization_id:
            raise ApiKeyAdminError("Valitun käyttäjän tulee kuulua valittuun organisaatioon.")

    api_key, raw_key = ApiKey.issue(
        name=name.strip(),
        organization_id=organization_id,
        user_id=user_id,
        scopes=",".join(selected_scopes),
        expires_at=expires_at,
    )
    db.session.add(api_key)
    db.session.flush()
    audit_admin_api_key_created(api_key=api_key, actor_id=actor_id, actor_email=actor_email)
    return api_key, raw_key


def toggle_api_key_active_admin(*, key_id: int, actor_id: int, actor_email: str | None) -> ApiKey:
    api_key = ApiKey.query.get_or_404(key_id)
    api_key.is_active = not api_key.is_active
    audit_admin_api_key_toggle(api_key=api_key, actor_id=actor_id, actor_email=actor_email)
    return api_key


def delete_api_key_admin(*, key_id: int, actor_id: int, actor_email: str | None) -> str:
    api_key = ApiKey.query.get_or_404(key_id)
    prefix = api_key.key_prefix
    audit_admin_api_key_deleted(
        key_id=key_id, prefix=prefix, actor_id=actor_id, actor_email=actor_email
    )
    db.session.delete(api_key)
    db.session.commit()
    return prefix


def get_unit_for_org_calendar_export(*, organization_id: int, unit_id: int) -> Unit | None:
    return (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Unit.id == unit_id, Property.organization_id == organization_id)
        .first()
    )


def prune_api_key_usage(*, retention_days: int) -> int:
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = (
        db.session.query(ApiKeyUsage)
        .filter(ApiKeyUsage.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.session.commit()
    return int(deleted or 0)
