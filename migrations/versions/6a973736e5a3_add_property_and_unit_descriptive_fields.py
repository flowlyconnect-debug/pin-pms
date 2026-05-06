"""add_property_and_unit_descriptive_fields

Revision ID: 6a973736e5a3
Revises: b8c9d0e1f2a3
Create Date: 2026-05-06 17:57:20.187466

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6a973736e5a3'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade():
    # Add descriptive property fields.
    with op.batch_alter_table('properties', schema=None) as batch_op:
        batch_op.add_column(sa.Column('city', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('postal_code', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('street_address', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('latitude', sa.Numeric(precision=10, scale=7), nullable=True))
        batch_op.add_column(sa.Column('longitude', sa.Numeric(precision=10, scale=7), nullable=True))
        batch_op.add_column(sa.Column('year_built', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('has_elevator', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('has_parking', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('has_sauna', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('has_courtyard', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('description', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('url', sa.String(length=500), nullable=True))
        batch_op.create_index(batch_op.f('ix_properties_city'), ['city'], unique=False)
    # Add descriptive unit fields.
    with op.batch_alter_table('units', schema=None) as batch_op:
        batch_op.add_column(sa.Column('floor', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('area_sqm', sa.Numeric(precision=6, scale=2), nullable=True))
        batch_op.add_column(sa.Column('bedrooms', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('has_kitchen', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('has_bathroom', sa.Boolean(), server_default=sa.true(), nullable=False))
        batch_op.add_column(sa.Column('has_balcony', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('has_terrace', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('has_dishwasher', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('has_washing_machine', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('has_tv', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('has_wifi', sa.Boolean(), server_default=sa.true(), nullable=False))
        batch_op.add_column(sa.Column('max_guests', sa.Integer(), server_default='2', nullable=False))
        batch_op.add_column(sa.Column('description', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('floor_plan_image_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(None, 'property_images', ['floor_plan_image_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('units', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_column('floor_plan_image_id')
        batch_op.drop_column('description')
        batch_op.drop_column('max_guests')
        batch_op.drop_column('has_wifi')
        batch_op.drop_column('has_tv')
        batch_op.drop_column('has_washing_machine')
        batch_op.drop_column('has_dishwasher')
        batch_op.drop_column('has_terrace')
        batch_op.drop_column('has_balcony')
        batch_op.drop_column('has_bathroom')
        batch_op.drop_column('has_kitchen')
        batch_op.drop_column('bedrooms')
        batch_op.drop_column('area_sqm')
        batch_op.drop_column('floor')

    with op.batch_alter_table('two_factor_email_codes', schema=None) as batch_op:
        batch_op.create_unique_constraint(batch_op.f('two_factor_email_codes_code_hash_key'), ['code_hash'], postgresql_nulls_not_distinct=False)

    with op.batch_alter_table('saved_filters', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_saved_filters_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('properties', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_properties_city'))
        batch_op.drop_column('url')
        batch_op.drop_column('description')
        batch_op.drop_column('has_courtyard')
        batch_op.drop_column('has_sauna')
        batch_op.drop_column('has_parking')
        batch_op.drop_column('has_elevator')
        batch_op.drop_column('year_built')
        batch_op.drop_column('longitude')
        batch_op.drop_column('latitude')
        batch_op.drop_column('street_address')
        batch_op.drop_column('postal_code')
        batch_op.drop_column('city')
