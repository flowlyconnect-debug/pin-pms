from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_

from app.audit import record as audit_record
from app.extensions import db
from app.notifications.models import Notification, NotificationSeverity
from app.users.models import User, UserRole


@dataclass
class NotificationServiceError(Exception):
    code: str
    message: str
    status: int


def _is_type_enabled_for_user(*, user: User | None, notification_type: str) -> bool:
    if user is None:
        return True
    raw_preferences = getattr(user, "preferences", None)
    if not isinstance(raw_preferences, dict):
        return True
    notif_preferences = raw_preferences.get("notifications")
    if not isinstance(notif_preferences, dict):
        return True
    disabled = notif_preferences.get("disabled_types")
    if not isinstance(disabled, list):
        return True
    return notification_type not in {str(item).strip() for item in disabled}


def create(
    organization_id: int,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    severity: str = NotificationSeverity.INFO,
    user_id: int | None = None,
) -> Notification | None:
    severity_value = (severity or NotificationSeverity.INFO).strip().lower()
    if severity_value not in NotificationSeverity.ALL:
        raise NotificationServiceError(
            code="validation_error",
            message="Invalid notification severity.",
            status=400,
        )

    target_user: User | None = None
    if user_id is not None:
        target_user = User.query.filter_by(id=user_id, organization_id=organization_id).first()
        if target_user is None:
            raise NotificationServiceError(
                code="not_found",
                message="User not found in organization.",
                status=404,
            )
        if not _is_type_enabled_for_user(user=target_user, notification_type=type):
            return None

    row = Notification(
        organization_id=organization_id,
        user_id=user_id,
        type=(type or "").strip(),
        title=(title or "").strip(),
        body=(body or "").strip() or None,
        link=(link or "").strip() or None,
        severity=severity_value,
        is_read=False,
    )
    db.session.add(row)
    db.session.flush()
    audit_record(
        "notification.created",
        target_type="notification",
        target_id=row.id,
        organization_id=organization_id,
        metadata={"type": row.type, "severity": row.severity},
        commit=False,
    )
    return row


def _get_visible_notification_for_user(*, notification_id: int, user: User) -> Notification:
    row = Notification.query.get(notification_id)
    if row is None:
        raise NotificationServiceError(code="not_found", message="Notification not found.", status=404)
    is_owner = row.user_id == user.id
    is_org_broadcast = row.user_id is None and row.organization_id == user.organization_id
    if not (is_owner or is_org_broadcast):
        raise NotificationServiceError(code="forbidden", message="Forbidden.", status=403)
    return row


def mark_read(notification_id: int, user_id: int) -> Notification:
    user = User.query.get(user_id)
    if user is None:
        raise NotificationServiceError(code="not_found", message="User not found.", status=404)
    row = _get_visible_notification_for_user(notification_id=notification_id, user=user)
    if not row.is_read:
        row.is_read = True
        row.read_at = datetime.utcnow()
        db.session.flush()
    return row


def mark_all_read(user_id: int, organization_id: int) -> int:
    user = User.query.get(user_id)
    if user is None:
        raise NotificationServiceError(code="not_found", message="User not found.", status=404)
    org_scope = organization_id
    if user.role != UserRole.SUPERADMIN.value and user.organization_id != organization_id:
        raise NotificationServiceError(code="forbidden", message="Forbidden.", status=403)
    if user.role != UserRole.SUPERADMIN.value:
        org_scope = user.organization_id
    rows = Notification.query.filter(
        Notification.organization_id == org_scope,
        Notification.is_read.is_(False),
        or_(Notification.user_id == user.id, Notification.user_id.is_(None)),
    ).all()
    now = datetime.utcnow()
    for row in rows:
        row.is_read = True
        row.read_at = now
    db.session.flush()
    return len(rows)


def list_unread(user_id: int, organization_id: int, limit: int = 50) -> list[Notification]:
    limited = max(1, min(int(limit or 50), 50))
    return (
        Notification.query.filter(
            Notification.organization_id == organization_id,
            Notification.is_read.is_(False),
            or_(Notification.user_id == user_id, Notification.user_id.is_(None)),
        )
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limited)
        .all()
    )


def list_all_for_user(
    *,
    user_id: int,
    organization_id: int,
    limit: int = 200,
) -> list[Notification]:
    limited = max(1, min(int(limit or 200), 200))
    return (
        Notification.query.filter(
            Notification.organization_id == organization_id,
            or_(Notification.user_id == user_id, Notification.user_id.is_(None)),
        )
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limited)
        .all()
    )


def unread_count(*, user_id: int, organization_id: int) -> int:
    return (
        Notification.query.filter(
            Notification.organization_id == organization_id,
            Notification.is_read.is_(False),
            or_(Notification.user_id == user_id, Notification.user_id.is_(None)),
        )
        .count()
    )


def prune_old(retention_days: int = 90) -> int:
    days = max(1, int(retention_days or 90))
    cutoff = datetime.utcnow() - timedelta(days=days)
    deleted = Notification.query.filter(Notification.created_at < cutoff).delete(synchronize_session=False)
    db.session.flush()
    return int(deleted or 0)

