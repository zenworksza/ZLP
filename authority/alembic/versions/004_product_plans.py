"""Add product_plans table

Revision ID: 004
Revises: 003
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'product_plans',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('product_id', UUID(as_uuid=True), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('default_seats', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('max_seats', sa.Integer(), nullable=True),
        sa.Column('features', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('idx_product_plans_product_id', 'product_plans', ['product_id'])
    op.create_unique_constraint('uq_product_plans_product_slug', 'product_plans', ['product_id', 'slug'])


def downgrade() -> None:
    op.drop_constraint('uq_product_plans_product_slug', 'product_plans', type_='unique')
    op.drop_index('idx_product_plans_product_id', table_name='product_plans')
    op.drop_table('product_plans')
