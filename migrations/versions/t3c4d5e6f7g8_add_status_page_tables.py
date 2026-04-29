"""add status page tables

Revision ID: t3c4d5e6f7g8
Revises: s2b3c4d5e6f7
Create Date: 2026-04-29 17:55:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "t3c4d5e6f7g8"
down_revision = "s2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "status_components",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("current_state", sa.String(length=32), nullable=False),
        sa.Column("scheduled_maintenance", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_status_components_current_state"), "status_components", ["current_state"], unique=False)
    op.create_index(op.f("ix_status_components_key"), "status_components", ["key"], unique=True)

    op.create_table(
        "status_incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("component_keys", sa.JSON(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_status_incidents_status"), "status_incidents", ["status"], unique=False)

    op.create_table(
        "status_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("component_key", sa.String(length=64), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_status_checks_checked_at"), "status_checks", ["checked_at"], unique=False)
    op.create_index(op.f("ix_status_checks_component_key"), "status_checks", ["component_key"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_status_checks_component_key"), table_name="status_checks")
    op.drop_index(op.f("ix_status_checks_checked_at"), table_name="status_checks")
    op.drop_table("status_checks")
    op.drop_index(op.f("ix_status_incidents_status"), table_name="status_incidents")
    op.drop_table("status_incidents")
    op.drop_index(op.f("ix_status_components_key"), table_name="status_components")
    op.drop_index(op.f("ix_status_components_current_state"), table_name="status_components")
    op.drop_table("status_components")
