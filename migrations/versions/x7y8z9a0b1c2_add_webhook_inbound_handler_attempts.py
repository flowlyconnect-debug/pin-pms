"""add webhook_events.inbound_handler_attempts

Revision ID: x7y8z9a0b1c2
Revises: 2b3c4d5e6f7a
Create Date: 2026-05-06 12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "x7y8z9a0b1c2"
down_revision = "2b3c4d5e6f7a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "webhook_events",
        sa.Column("inbound_handler_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("webhook_events", "inbound_handler_attempts", server_default=None)


def downgrade() -> None:
    op.drop_column("webhook_events", "inbound_handler_attempts")
