"""Add reservation invoicing fields

Revision ID: b9c1d2e3f4a5
Revises: f1c2d3e4b5a6
Create Date: 2026-04-26 22:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "b9c1d2e3f4a5"
down_revision = "f1c2d3e4b5a6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("reservations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("amount", sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR")
        )
        batch_op.add_column(
            sa.Column(
                "payment_status",
                sa.String(length=20),
                nullable=False,
                server_default="pending",
            )
        )


def downgrade():
    with op.batch_alter_table("reservations", schema=None) as batch_op:
        batch_op.drop_column("payment_status")
        batch_op.drop_column("currency")
        batch_op.drop_column("amount")
