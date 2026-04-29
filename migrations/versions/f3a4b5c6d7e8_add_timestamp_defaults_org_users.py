"""Add server defaults for organizations/users created_at (legacy NOT NULL columns).

Revision ID: f3a4b5c6d7e8
Revises: a9b8c7d6e5f4
Create Date: 2026-04-27

The initial user/org migration created ``created_at`` as NOT NULL without a
database default; inserts that rely on the ORM omitting the column then fail
on Alembic-managed databases. Align with newer tables that use ``now()``.
"""

import sqlalchemy as sa
from alembic import op

revision = "f3a4b5c6d7e8"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "organizations",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def downgrade():
    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
        nullable=False,
    )
    op.alter_column(
        "organizations",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
        nullable=False,
    )
