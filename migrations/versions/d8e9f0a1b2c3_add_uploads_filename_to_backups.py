"""Add uploads_filename column to backups table.

Project brief section 8: backups must include uploaded files alongside the
SQL dump. The new column tracks the optional uploads tar.gz sibling so
restore can pair the two files.

Revision ID: d8e9f0a1b2c3
Revises: c3d4e5f6a7b8
Create Date: 2026-04-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d8e9f0a1b2c3"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "backups",
        sa.Column("uploads_filename", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("backups", "uploads_filename")
