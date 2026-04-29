"""Add backup_codes column to users for 2FA recovery.

Project brief section 5: superadmin 2FA needs recovery codes for the
case where the authenticator app is lost. The column holds a JSON list
of SHA-256 hex digests so plaintext is never persisted.

Revision ID: e0f1a2b3c4d5
Revises: d8e9f0a1b2c3
Create Date: 2026-04-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e0f1a2b3c4d5"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "backup_codes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    # Drop the server default after backfill — application-level default
    # ([]) is the source of truth going forward.
    op.alter_column("users", "backup_codes", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "backup_codes")
