"""add two factor email codes

Revision ID: l5e6f7g8h9i0
Revises: j2b3c4d5e6f7
Create Date: 2026-04-28 18:15:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "l5e6f7g8h9i0"
down_revision = "j2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "two_factor_email_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index(
        op.f("ix_two_factor_email_codes_user_id"),
        "two_factor_email_codes",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_two_factor_email_codes_code_hash"),
        "two_factor_email_codes",
        ["code_hash"],
        unique=True,
    )


def downgrade():
    op.drop_index(op.f("ix_two_factor_email_codes_code_hash"), table_name="two_factor_email_codes")
    op.drop_index(op.f("ix_two_factor_email_codes_user_id"), table_name="two_factor_email_codes")
    op.drop_table("two_factor_email_codes")
