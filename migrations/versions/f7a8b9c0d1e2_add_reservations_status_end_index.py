"""add reservations status+end_date and status+start_date indexes

Revision ID: f7a8b9c0d1e2
Revises: 51aed2f30e48
Create Date: 2026-05-09 09:00:00

Tukee `list_units_with_availability_status`-funktion ja muiden saatavuus-
laskelmien suorituskykyä lisäämällä reservations-tauluun status- ja päivämäärä-
sarakkeisiin perustuvat yhdistelmäindeksit. Hakuja, joissa rajataan
aktiiviseen tilaan ja tulevaan päättymis- tai alkamispäivään, voidaan tukea
ilman täydellistä taulun läpikäyntiä.
"""

from alembic import op


revision = "f7a8b9c0d1e2"
down_revision = "51aed2f30e48"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_reservations_status_end_date",
        "reservations",
        ["status", "end_date"],
        unique=False,
    )
    op.create_index(
        "ix_reservations_status_start_date",
        "reservations",
        ["status", "start_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_reservations_status_start_date", table_name="reservations")
    op.drop_index("ix_reservations_status_end_date", table_name="reservations")
