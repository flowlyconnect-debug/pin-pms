"""add backup json export filenames

Init template §8: backups must include human-readable exports of email
templates and settings alongside the SQL dump. Track the JSON sibling
filenames so retention pruning and selective restore can locate them.

Revision ID: d9a1b2c3e4f5
Revises: c7d8e9f0a1b2
Create Date: 2026-05-07 19:10:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d9a1b2c3e4f5"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "backups",
        sa.Column("email_templates_filename", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "backups",
        sa.Column("settings_filename", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("backups", "settings_filename")
    op.drop_column("backups", "email_templates_filename")
