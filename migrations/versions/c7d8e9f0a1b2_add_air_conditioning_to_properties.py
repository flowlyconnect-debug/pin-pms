"""add air conditioning to properties

Revision ID: c7d8e9f0a1b2
Revises: f1b2c3d4e5f6
Create Date: 2026-05-07 10:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c7d8e9f0a1b2"
down_revision = "f1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "properties",
        sa.Column("has_air_conditioning", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("properties", "has_air_conditioning", server_default=None)


def downgrade():
    op.drop_column("properties", "has_air_conditioning")
