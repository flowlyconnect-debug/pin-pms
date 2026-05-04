"""add_anonymized_at_to_users

Revision ID: a1b2c3d4e5f7
Revises: 12f7eacdab45
Create Date: 2026-05-04 14:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f7"
down_revision = "12f7eacdab45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("first_name", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("last_name", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("phone", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("address", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("anonymized_at")
        batch_op.drop_column("address")
        batch_op.drop_column("phone")
        batch_op.drop_column("last_name")
        batch_op.drop_column("first_name")
