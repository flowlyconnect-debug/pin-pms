"""add login attempts table

Revision ID: q9e0f1a2b3c4
Revises: p8d9e0f1a2b3
Create Date: 2026-04-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "q9e0f1a2b3c4"
down_revision = "p8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_login_attempts_email"),
        "login_attempts",
        ["email"],
        unique=False,
    )
    op.create_index(
        op.f("ix_login_attempts_success"),
        "login_attempts",
        ["success"],
        unique=False,
    )
    op.create_index(
        op.f("ix_login_attempts_created_at"),
        "login_attempts",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_login_attempts_created_at"), table_name="login_attempts")
    op.drop_index(op.f("ix_login_attempts_success"), table_name="login_attempts")
    op.drop_index(op.f("ix_login_attempts_email"), table_name="login_attempts")
    op.drop_table("login_attempts")
