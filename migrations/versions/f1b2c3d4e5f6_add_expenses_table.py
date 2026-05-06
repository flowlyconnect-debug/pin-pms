"""add expenses table

Revision ID: f1b2c3d4e5f6
Revises: 6a973736e5a3
Create Date: 2026-05-06 18:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f1b2c3d4e5f6"
down_revision = "6a973736e5a3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("vat", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("payee", sa.String(length=255), nullable=True),
        sa.Column("attached_invoice_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["attached_invoice_id"], ["invoices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_expenses_organization_id"), "expenses", ["organization_id"], unique=False)
    op.create_index(op.f("ix_expenses_property_id"), "expenses", ["property_id"], unique=False)
    op.create_index(op.f("ix_expenses_category"), "expenses", ["category"], unique=False)
    op.create_index(op.f("ix_expenses_date"), "expenses", ["date"], unique=False)
    op.create_index(
        op.f("ix_expenses_attached_invoice_id"), "expenses", ["attached_invoice_id"], unique=False
    )


def downgrade():
    op.drop_index(op.f("ix_expenses_attached_invoice_id"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_date"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_category"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_property_id"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_organization_id"), table_name="expenses")
    op.drop_table("expenses")
