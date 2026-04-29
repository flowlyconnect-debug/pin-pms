"""add owner portal tables

Revision ID: s2b3c4d5e6f7
Revises: r1a2b3c4d5e6
Create Date: 2026-04-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "s2b3c4d5e6f7"
down_revision = "r1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "property_owners",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("payout_iban", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_property_owners_organization_id", "property_owners", ["organization_id"])
    op.create_index("ix_property_owners_email", "property_owners", ["email"])

    op.create_table(
        "property_owner_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("ownership_pct", sa.Numeric(5, 4), nullable=False),
        sa.Column("management_fee_pct", sa.Numeric(5, 4), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["property_owners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_property_owner_assignments_property_id", "property_owner_assignments", ["property_id"])
    op.create_index("ix_property_owner_assignments_owner_id", "property_owner_assignments", ["owner_id"])

    op.create_table(
        "owner_payouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.String(length=7), nullable=False),
        sa.Column("gross_revenue_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("management_fee_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expenses_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("net_payout_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("pdf_path", sa.String(length=512), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["property_owners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_owner_payouts_owner_id", "owner_payouts", ["owner_id"])
    op.create_index("ix_owner_payouts_period_month", "owner_payouts", ["period_month"])
    op.create_unique_constraint("uq_owner_payout_owner_month", "owner_payouts", ["owner_id", "period_month"])

    op.create_table(
        "owner_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["property_owners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_owner_users_owner_id", "owner_users", ["owner_id"])
    op.create_index("ix_owner_users_email", "owner_users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_owner_users_email", table_name="owner_users")
    op.drop_index("ix_owner_users_owner_id", table_name="owner_users")
    op.drop_table("owner_users")
    op.drop_constraint("uq_owner_payout_owner_month", "owner_payouts", type_="unique")
    op.drop_index("ix_owner_payouts_period_month", table_name="owner_payouts")
    op.drop_index("ix_owner_payouts_owner_id", table_name="owner_payouts")
    op.drop_table("owner_payouts")
    op.drop_index("ix_property_owner_assignments_owner_id", table_name="property_owner_assignments")
    op.drop_index("ix_property_owner_assignments_property_id", table_name="property_owner_assignments")
    op.drop_table("property_owner_assignments")
    op.drop_index("ix_property_owners_email", table_name="property_owners")
    op.drop_index("ix_property_owners_organization_id", table_name="property_owners")
    op.drop_table("property_owners")
