"""Audit-log model.

Each row captures one security- or governance-relevant event. The schema is
denormalized on purpose: we copy ``actor_email`` and other human-readable
fields directly onto the row so the log remains readable even if the related
user, API key, or organization is later renamed or deleted.

Actions follow a dotted namespace (``domain.subject.outcome``) so they are
easy to filter on — e.g. ``auth.login.success`` vs ``auth.login.failure``,
``apikey.created``, ``user.created``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


class ActorType:
    """String constants for ``AuditLog.actor_type``.

    Defined as a plain class (not an Enum) so values can be used directly in
    queries and inserts without conversion. Keeping them as strings also keeps
    database migrations simple.
    """

    USER = "user"
    API_KEY = "api_key"
    SYSTEM = "system"
    ANONYMOUS = "anonymous"


class AuditStatus:
    """String constants for ``AuditLog.status``."""

    SUCCESS = "success"
    FAILURE = "failure"


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # --- Actor (who did it) ---------------------------------------------
    actor_type = db.Column(db.String(32), nullable=False, index=True)
    actor_id = db.Column(db.Integer, nullable=True, index=True)
    # Denormalized so the log stays readable after an actor is renamed/deleted.
    actor_email = db.Column(db.String(255), nullable=True)

    # --- Tenant scope ----------------------------------------------------
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # --- Action (what happened) -----------------------------------------
    action = db.Column(db.String(128), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=True)

    # --- Target (what it happened to) -----------------------------------
    target_type = db.Column(db.String(64), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)

    # --- Request metadata -----------------------------------------------
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)

    # Extra structured context (IDs, reason codes, etc.). Named ``context``
    # because ``metadata`` is reserved on SQLAlchemy declarative models.
    context = db.Column(db.JSON, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<AuditLog #{self.id} {self.created_at.isoformat() if self.created_at else '?'} "
            f"{self.actor_type}:{self.actor_id} {self.action} {self.status or '-'}>"
        )
