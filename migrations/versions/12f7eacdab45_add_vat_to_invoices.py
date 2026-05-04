"""add_vat_to_invoices

Revision ID: 12f7eacdab45
Revises: w6f7g8h9i0j1
Create Date: 2026-05-04 16:26:21.274393

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "12f7eacdab45"
down_revision = "w6f7g8h9i0j1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add VAT columns and treat legacy ``amount`` as total including 24 % VAT."""

    with op.batch_alter_table("invoices", schema=None) as batch_op:
        batch_op.add_column(sa.Column("vat_rate", sa.Numeric(5, 2), nullable=True))
        batch_op.add_column(sa.Column("vat_amount", sa.Numeric(12, 2), nullable=True))
        batch_op.add_column(sa.Column("subtotal_excl_vat", sa.Numeric(12, 2), nullable=True))
        batch_op.add_column(sa.Column("total_incl_vat", sa.Numeric(12, 2), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE invoices SET
              vat_rate = 24.00,
              total_incl_vat = amount,
              subtotal_excl_vat = ROUND((amount / 1.24)::numeric, 2),
              vat_amount = amount - ROUND((amount / 1.24)::numeric, 2)
            """
        )
    )

    with op.batch_alter_table("invoices", schema=None) as batch_op:
        batch_op.alter_column(
            "vat_rate",
            existing_type=sa.Numeric(5, 2),
            nullable=False,
            server_default="24.00",
        )
        batch_op.alter_column(
            "vat_amount",
            existing_type=sa.Numeric(12, 2),
            nullable=False,
            server_default="0.00",
        )
        batch_op.alter_column(
            "subtotal_excl_vat",
            existing_type=sa.Numeric(12, 2),
            nullable=False,
            server_default="0.00",
        )
        batch_op.alter_column(
            "total_incl_vat",
            existing_type=sa.Numeric(12, 2),
            nullable=False,
            server_default="0.00",
        )


def downgrade() -> None:
    with op.batch_alter_table("invoices", schema=None) as batch_op:
        batch_op.drop_column("total_incl_vat")
        batch_op.drop_column("subtotal_excl_vat")
        batch_op.drop_column("vat_amount")
        batch_op.drop_column("vat_rate")
