from __future__ import annotations

from datetime import datetime

from app.extensions import db


class NotificationSeverity:
    INFO = "info"
    WARNING = "warning"
    DANGER = "danger"
    SUCCESS = "success"

    ALL = (INFO, WARNING, DANGER, SUCCESS)


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    type = db.Column(db.String(128), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=True)
    link = db.Column(db.String(512), nullable=True)
    severity = db.Column(db.String(32), nullable=False, default=NotificationSeverity.INFO, index=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    read_at = db.Column(db.DateTime, nullable=True)

