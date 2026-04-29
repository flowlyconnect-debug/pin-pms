from __future__ import annotations

from app.extensions import db


class SubscriptionPlan(db.Model):
    __tablename__ = "subscription_plans"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), nullable=False, unique=True, index=True)
    name = db.Column(db.String(255), nullable=False)
    limits_json = db.Column(db.JSON, nullable=False, default=dict)
