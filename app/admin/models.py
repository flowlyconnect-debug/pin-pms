from __future__ import annotations

from datetime import datetime

from app.extensions import db


class SavedFilter(db.Model):
    __tablename__ = "saved_filters"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(128), nullable=False)
    view_type = db.Column(db.String(64), nullable=False)
    filter_params = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
