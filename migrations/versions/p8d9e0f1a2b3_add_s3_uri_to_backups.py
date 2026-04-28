"""Add s3_uri column to backups table.

Revision ID: p8d9e0f1a2b3
Revises: n7c8d9e0f1a2
Create Date: 2026-04-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "p8d9e0f1a2b3"
down_revision = "n7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backups", sa.Column("s3_uri", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("backups", "s3_uri")
