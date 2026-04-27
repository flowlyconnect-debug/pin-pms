from datetime import datetime, timezone

import sqlalchemy as sa

from app.extensions import db


class TimestampMixin:
    """Shared created/updated timestamp columns for domain models."""

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
