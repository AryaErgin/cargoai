"""ocean fcl pricing fx and audit snapshots

Revision ID: 0002_pricing
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa


revision = '0002_pricing'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('exchange_rates',
    sa.Column('base_currency', sa.String(length=3), nullable=False),
    sa.Column('quote_currency', sa.String(length=3), nullable=False),
    sa.Column('rate', sa.Numeric(precision=18, scale=8), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('source', sa.String(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('effective_to IS NULL OR effective_from <= effective_to', name=op.f('ck_exchange_rates_fx_validity_order')),
    sa.CheckConstraint('rate > 0', name=op.f('ck_exchange_rates_positive_fx_rate')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_exchange_rates_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_exchange_rates')),
    sa.UniqueConstraint('tenant_id', 'base_currency', 'quote_currency', 'effective_from', name='uq_fx_pair_start'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_exchange_rates_tenant_id'))
    )
    op.create_index(op.f('ix_exchange_rates_tenant_id'), 'exchange_rates', ['tenant_id'], unique=False)
    op.create_index('ix_fx_lookup', 'exchange_rates', ['tenant_id', 'base_currency', 'quote_currency', 'effective_from', 'effective_to'], unique=False)
    op.add_column('quote_lines', sa.Column('calculation_json', sa.JSON(), nullable=True))
    op.add_column('quotes', sa.Column('calculation_json', sa.JSON(), nullable=True))
    op.add_column('rate_charges', sa.Column('percentage_base', sa.String(16),
        sa.CheckConstraint("percentage_base IN ('FREIGHT_SUBTOTAL', 'BUY_SUBTOTAL')", name='ck_rate_charges_percentage_base'),
        nullable=True))


def downgrade():
    op.drop_column('rate_charges', 'percentage_base')
    op.drop_column('quotes', 'calculation_json')
    op.drop_column('quote_lines', 'calculation_json')
    op.drop_index('ix_fx_lookup', table_name='exchange_rates')
    op.drop_index(op.f('ix_exchange_rates_tenant_id'), table_name='exchange_rates')
    op.drop_table('exchange_rates')
