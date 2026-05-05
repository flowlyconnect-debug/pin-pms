from __future__ import annotations

from datetime import datetime

from app.extensions import db


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    target_type = db.Column(db.String(32), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    author_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    edited_at = db.Column(db.DateTime, nullable=True)
    is_internal = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (
        db.Index("ix_comments_org_target", "organization_id", "target_type", "target_id"),
        db.Index("ix_comments_author_user_id", "author_user_id"),
    )
