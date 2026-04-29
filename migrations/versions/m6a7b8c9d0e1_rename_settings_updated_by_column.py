"""Rename settings.updated_by_id to updated_by.

Revision ID: m6a7b8c9d0e1
Revises: k4d5e6f7g8h9
Create Date: 2026-04-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m6a7b8c9d0e1"
down_revision = "k4d5e6f7g8h9"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    if _has_column("settings", "updated_by_id") and not _has_column("settings", "updated_by"):
        with op.batch_alter_table("settings") as batch_op:
            batch_op.alter_column("updated_by_id", new_column_name="updated_by")


def downgrade() -> None:
    if _has_column("settings", "updated_by") and not _has_column("settings", "updated_by_id"):
        with op.batch_alter_table("settings") as batch_op:
            batch_op.alter_column("updated_by", new_column_name="updated_by_id")
