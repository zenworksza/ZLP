"""Add renewal cycles, customer email, plan pricing, and invoices table

Revision ID: 005
Revises: 004
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add renewal_period_days and customer_email to license_keys
    op.add_column('license_keys', sa.Column('renewal_period_days', sa.Integer(), nullable=True))
    op.add_column('license_keys', sa.Column('customer_email', sa.String(), nullable=True))

    # Add price_cents to product_plans (price per 30-day period in cents)
    op.add_column('product_plans', sa.Column('price_cents', sa.Integer(), nullable=True))

    # Invoices table
    op.create_table(
        'invoices',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('license_key_id', UUID(as_uuid=True), sa.ForeignKey('license_keys.id', ondelete='CASCADE'), nullable=False),
        sa.Column('invoice_number', sa.String(), nullable=False, unique=True),
        sa.Column('period_days', sa.Integer(), nullable=False),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='ZAR'),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('idx_invoices_license_key_id', 'invoices', ['license_key_id'])
    op.create_index('idx_invoices_status', 'invoices', ['status'])
    op.create_index('idx_invoices_due_date', 'invoices', ['due_date'])


def downgrade() -> None:
    op.drop_index('idx_invoices_due_date', table_name='invoices')
    op.drop_index('idx_invoices_status', table_name='invoices')
    op.drop_index('idx_invoices_license_key_id', table_name='invoices')
    op.drop_table('invoices')
    op.drop_column('product_plans', 'price_cents')
    op.drop_column('license_keys', 'customer_email')
    op.drop_column('license_keys', 'renewal_period_days')
