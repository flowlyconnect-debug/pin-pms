"""add saved filters

Revision ID: z9f8e7d6c5b4
Revises: h1a2b3c4d5e6
Create Date: 2026-05-05 15:50:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "z9f8e7d6c5b4"
down_revision = "h1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "saved_filters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("view_type", sa.String(length=64), nullable=False),
        sa.Column("filter_params", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_saved_filters_user_id"), "saved_filters", ["user_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_saved_filters_user_id"), table_name="saved_filters")
    op.drop_table("saved_filters")

