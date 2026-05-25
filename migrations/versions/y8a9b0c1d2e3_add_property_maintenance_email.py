"""add property maintenance_email

Revision ID: y8a9b0c1d2e3
Revises: f7a8b9c0d1e2
Create Date: 2026-05-25 13:50:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "y8a9b0c1d2e3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "properties",
        sa.Column("maintenance_email", sa.String(length=255), nullable=True),
    )

    from app.settings.seed_data import SEED_SETTINGS

    bind = op.get_bind()
    existing = {row[0] for row in bind.execute(sa.text("SELECT key FROM settings"))}
    table = sa.table(
        "settings",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("type", sa.String),
        sa.column("description", sa.String),
        sa.column("is_secret", sa.Boolean),
    )
    new_rows = [s for s in SEED_SETTINGS if s["key"] not in existing]
    if new_rows:
        bind.execute(
            table.insert(),
            [
                {
                    "key": s["key"],
                    "value": s["value"],
                    "type": s["type"],
                    "description": s["description"],
                    "is_secret": s["is_secret"],
                }
                for s in new_rows
            ],
        )


def downgrade():
    op.drop_column("properties", "maintenance_email")
    op.execute(
        sa.text(
            "DELETE FROM settings WHERE key IN "
            "('maintenance.default_email', 'maintenance.email_notifications_enabled')"
        )
    )
