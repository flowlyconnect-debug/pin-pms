"""add portal magic link tokens

Revision ID: h1a2b3c4d5e6
Revises: g4b5c6d7e8f0
Create Date: 2026-04-27 08:55:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "h1a2b3c4d5e6"
down_revision = "g4b5c6d7e8f0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "portal_magic_link_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_portal_magic_link_tokens_user_id"),
        "portal_magic_link_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_portal_magic_link_tokens_token_hash"),
        "portal_magic_link_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade():
    op.drop_index(op.f("ix_portal_magic_link_tokens_token_hash"), table_name="portal_magic_link_tokens")
    op.drop_index(op.f("ix_portal_magic_link_tokens_user_id"), table_name="portal_magic_link_tokens")
    op.drop_table("portal_magic_link_tokens")

