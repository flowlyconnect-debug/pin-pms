"""add_idempotency_keys_table

Revision ID: e9f0a1b2c3d4
Revises: a1b2c3d4e5f7
Create Date: 2026-05-04 18:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e9f0a1b2c3d4"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("endpoint", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("idempotency_keys", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_idempotency_keys_expires_at"), ["expires_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_idempotency_keys_key"), ["key"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("idempotency_keys", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_idempotency_keys_key"))
        batch_op.drop_index(batch_op.f("ix_idempotency_keys_expires_at"))

    op.drop_table("idempotency_keys")
