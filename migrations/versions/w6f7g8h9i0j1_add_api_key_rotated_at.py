"""add rotated_at to api keys

Revision ID: w6f7g8h9i0j1
Revises: v5e6f7g8h9i0
Create Date: 2026-05-03 18:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "w6f7g8h9i0j1"
down_revision = "v5e6f7g8h9i0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.drop_column("rotated_at")
