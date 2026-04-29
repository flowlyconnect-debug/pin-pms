"""add api key usage table

Revision ID: n7c8d9e0f1a2
Revises: h1a2b3c4d5e6
Create Date: 2026-04-28 18:50:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "n7c8d9e0f1a2"
down_revision = "h1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_key_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("api_key_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_api_key_usage_api_key_id"), "api_key_usage", ["api_key_id"], unique=False)
    op.create_index(op.f("ix_api_key_usage_created_at"), "api_key_usage", ["created_at"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_api_key_usage_created_at"), table_name="api_key_usage")
    op.drop_index(op.f("ix_api_key_usage_api_key_id"), table_name="api_key_usage")
    op.drop_table("api_key_usage")
