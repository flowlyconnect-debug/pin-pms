"""Add backups table.

Revision ID: d7e4f8a2b3c1
Revises: c4d8e3f1a9b2
Create Date: 2026-04-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d7e4f8a2b3c1"
down_revision = "c4d8e3f1a9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(length=255), nullable=False, unique=True),
        sa.Column("location", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "trigger",
            sa.String(length=16),
            nullable=False,
            server_default="scheduled",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_backups_filename", "backups", ["filename"], unique=True)
    op.create_index("ix_backups_status", "backups", ["status"], unique=False)
    op.create_index("ix_backups_created_at", "backups", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_backups_created_at", table_name="backups")
    op.drop_index("ix_backups_status", table_name="backups")
    op.drop_index("ix_backups_filename", table_name="backups")
    op.drop_table("backups")
