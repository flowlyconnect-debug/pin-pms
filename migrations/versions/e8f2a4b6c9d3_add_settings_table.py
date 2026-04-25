"""Add settings table and seed default rows.

Revision ID: e8f2a4b6c9d3
Revises: d7e4f8a2b3c1
Create Date: 2026-04-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e8f2a4b6c9d3"
down_revision = "d7e4f8a2b3c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=False, server_default="string"),
        sa.Column(
            "description",
            sa.String(length=255),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "is_secret",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "updated_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_settings_key", "settings", ["key"], unique=True)

    # Seed the default rows.
    from app.settings.seed_data import SEED_SETTINGS

    bind = op.get_bind()
    table = sa.table(
        "settings",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("type", sa.String),
        sa.column("description", sa.String),
        sa.column("is_secret", sa.Boolean),
    )

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
            for s in SEED_SETTINGS
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_settings_key", table_name="settings")
    op.drop_table("settings")
