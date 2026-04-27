"""Add reservation invoice metadata

Revision ID: c3d4e5f6a7b8
Revises: b9c1d2e3f4a5
Create Date: 2026-04-26 22:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b9c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("reservations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("invoice_number", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("invoice_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("due_date", sa.Date(), nullable=True))
        batch_op.create_unique_constraint("uq_reservations_invoice_number", ["invoice_number"])


def downgrade():
    with op.batch_alter_table("reservations", schema=None) as batch_op:
        batch_op.drop_constraint("uq_reservations_invoice_number", type_="unique")
        batch_op.drop_column("due_date")
        batch_op.drop_column("invoice_date")
        batch_op.drop_column("invoice_number")
