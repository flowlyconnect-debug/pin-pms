"""add subscription plans and org plan reference

Revision ID: v5e6f7g8h9i0
Revises: u4d5e6f7g8h9
Create Date: 2026-04-29 18:52:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "v5e6f7g8h9i0"
down_revision = "u4d5e6f7g8h9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("limits_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("subscription_plans", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_subscription_plans_code"), ["code"], unique=True)

    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("subscription_plan_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_organizations_subscription_plan_id"),
            ["subscription_plan_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_organizations_subscription_plan_id",
            "subscription_plans",
            ["subscription_plan_id"],
            ["id"],
        )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO subscription_plans (code, name, limits_json)
            VALUES
              ('free', 'Free', :free_limits),
              ('pro', 'Pro', :pro_limits),
              ('enterprise', 'Enterprise', :enterprise_limits)
            """
        ),
        {
            "free_limits": '{"api_rate_limit":"100/hour"}',
            "pro_limits": '{"api_rate_limit":"1000/hour"}',
            "enterprise_limits": '{"api_rate_limit":"10000/hour"}',
        },
    )
    conn.execute(
        sa.text(
            """
            UPDATE organizations
            SET subscription_plan_id = (
              SELECT id FROM subscription_plans WHERE code = 'free'
            )
            WHERE subscription_plan_id IS NULL
            """
        )
    )


def downgrade():
    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.drop_constraint("fk_organizations_subscription_plan_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_organizations_subscription_plan_id"))
        batch_op.drop_column("subscription_plan_id")

    with op.batch_alter_table("subscription_plans", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_subscription_plans_code"))
    op.drop_table("subscription_plans")
