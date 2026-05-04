"""add_webhook_infrastructure

Revision ID: a7b8c9d0e1f2
Revises: e9f0a1b2c3d4
Create Date: 2026-05-04 20:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("signature", sa.String(length=256), nullable=False),
        sa.Column("signature_verified", sa.Boolean(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("webhook_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_webhook_events_organization_id"), ["organization_id"], unique=False
        )
        batch_op.create_index(
            "ix_webhook_events_provider_processed",
            ["provider", "processed"],
            unique=False,
        )
        batch_op.create_unique_constraint(
            "uq_webhook_events_provider_external_id",
            ["provider", "external_id"],
        )

    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_status", sa.Integer(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("webhook_subscriptions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_webhook_subscriptions_organization_id"),
            ["organization_id"],
            unique=False,
        )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.String(length=256), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["webhook_subscriptions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("webhook_deliveries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_webhook_deliveries_subscription_id"),
            ["subscription_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_webhook_deliveries_next_retry_at"),
            ["next_retry_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("webhook_deliveries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_webhook_deliveries_next_retry_at"))
        batch_op.drop_index(batch_op.f("ix_webhook_deliveries_subscription_id"))

    op.drop_table("webhook_deliveries")

    with op.batch_alter_table("webhook_subscriptions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_webhook_subscriptions_organization_id"))

    op.drop_table("webhook_subscriptions")

    with op.batch_alter_table("webhook_events", schema=None) as batch_op:
        batch_op.drop_constraint("uq_webhook_events_provider_external_id", type_="unique")
        batch_op.drop_index("ix_webhook_events_provider_processed")
        batch_op.drop_index(batch_op.f("ix_webhook_events_organization_id"))

    op.drop_table("webhook_events")
