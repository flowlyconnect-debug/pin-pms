"""Add maintenance_requests table (tenant-scoped work orders).

Revision ID: g4b5c6d7e8f0
Revises: f3a4b5c6d7e8
Create Date: 2026-04-27
"""

import sqlalchemy as sa
from alembic import op

revision = "g4b5c6d7e8f0"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "maintenance_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("guest_id", sa.Integer(), nullable=True),
        sa.Column("reservation_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("assigned_to_id", sa.Integer(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["guest_id"], ["guests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_maintenance_requests_organization_id"),
        "maintenance_requests",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_maintenance_requests_property_id"),
        "maintenance_requests",
        ["property_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_maintenance_requests_unit_id"),
        "maintenance_requests",
        ["unit_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_maintenance_requests_guest_id"),
        "maintenance_requests",
        ["guest_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_maintenance_requests_reservation_id"),
        "maintenance_requests",
        ["reservation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_maintenance_requests_status"),
        "maintenance_requests",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_maintenance_requests_priority"),
        "maintenance_requests",
        ["priority"],
        unique=False,
    )
    op.create_index(
        op.f("ix_maintenance_requests_assigned_to_id"),
        "maintenance_requests",
        ["assigned_to_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_maintenance_requests_due_date"),
        "maintenance_requests",
        ["due_date"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_maintenance_requests_due_date"), table_name="maintenance_requests")
    op.drop_index(op.f("ix_maintenance_requests_assigned_to_id"), table_name="maintenance_requests")
    op.drop_index(op.f("ix_maintenance_requests_priority"), table_name="maintenance_requests")
    op.drop_index(op.f("ix_maintenance_requests_status"), table_name="maintenance_requests")
    op.drop_index(op.f("ix_maintenance_requests_reservation_id"), table_name="maintenance_requests")
    op.drop_index(op.f("ix_maintenance_requests_guest_id"), table_name="maintenance_requests")
    op.drop_index(op.f("ix_maintenance_requests_unit_id"), table_name="maintenance_requests")
    op.drop_index(op.f("ix_maintenance_requests_property_id"), table_name="maintenance_requests")
    op.drop_index(op.f("ix_maintenance_requests_organization_id"), table_name="maintenance_requests")
    op.drop_table("maintenance_requests")
