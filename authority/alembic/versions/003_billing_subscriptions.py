"""Add billing_subscriptions table

Revision ID: 003
Revises: 002
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'billing_subscriptions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('license_key_id', UUID(as_uuid=True), sa.ForeignKey('license_keys.id', ondelete='CASCADE'), nullable=False),
        sa.Column('gateway', sa.String(), nullable=False),
        sa.Column('gateway_ref', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='active'),
        sa.Column('overdue_since', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_payment_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint('uq_billing_subscriptions_gateway_ref', 'billing_subscriptions', ['gateway_ref'])
    op.create_index('idx_billing_subscriptions_gateway_ref', 'billing_subscriptions', ['gateway_ref'], unique=True)
    op.create_index('idx_billing_subscriptions_license_key_id', 'billing_subscriptions', ['license_key_id'])


def downgrade() -> None:
    op.drop_index('idx_billing_subscriptions_license_key_id', table_name='billing_subscriptions')
    op.drop_index('idx_billing_subscriptions_gateway_ref', table_name='billing_subscriptions')
    op.drop_constraint('uq_billing_subscriptions_gateway_ref', 'billing_subscriptions', type_='unique')
    op.drop_table('billing_subscriptions')
