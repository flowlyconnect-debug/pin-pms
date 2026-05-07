"""add reservation availability index

Revision ID: e1f2a3b4c5d6
Revises: d9a1b2c3e4f5
Create Date: 2026-05-07 19:31:00
"""

from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d9a1b2c3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_reservations_unit_start_end",
        "reservations",
        ["unit_id", "start_date", "end_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_reservations_unit_start_end", table_name="reservations")
