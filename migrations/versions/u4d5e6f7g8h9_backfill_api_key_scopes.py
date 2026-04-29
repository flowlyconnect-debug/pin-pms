"""backfill api key scopes to reservations and invoices wildcard

Revision ID: u4d5e6f7g8h9
Revises: t3c4d5e6f7g8
Create Date: 2026-04-29 18:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "u4d5e6f7g8h9"
down_revision = "t3c4d5e6f7g8"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, scopes FROM api_keys")).fetchall()
    for row in rows:
        raw_scopes = (row.scopes or "").strip()
        if raw_scopes:
            continue
        conn.execute(
            sa.text("UPDATE api_keys SET scopes = :scopes WHERE id = :id"),
            {"scopes": "reservations:*,invoices:*", "id": row.id},
        )


def downgrade():
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE api_keys SET scopes = '' "
            "WHERE scopes = 'reservations:*,invoices:*'"
        )
    )
