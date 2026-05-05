"""add payment refund error and idempotency

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-05-05 18:05:00
"""

from alembic import op
import sqlalchemy as sa


revision = "2b3c4d5e6f7a"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payment_refunds", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.add_column("payment_refunds", sa.Column("last_error", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_payment_refunds_idempotency_key", "payment_refunds", ["idempotency_key"])


def downgrade() -> None:
    op.drop_constraint("uq_payment_refunds_idempotency_key", "payment_refunds", type_="unique")
    op.drop_column("payment_refunds", "last_error")
    op.drop_column("payment_refunds", "idempotency_key")

