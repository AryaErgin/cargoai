"""initial shared multi-tenant storage

Revision ID: 0001_initial
Revises: 
"""
from alembic import op
import sqlalchemy as sa


revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('charge_types',
    sa.Column('canonical_code', sa.String(length=100), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('category', sa.Enum('FREIGHT', 'ORIGIN', 'DESTINATION', 'DOCUMENTATION', 'SECURITY', 'SURCHARGE', 'INLAND', 'CUSTOMS', 'OTHER', name='charge_category', native_enum=False, create_constraint=False), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("category IN ('FREIGHT', 'ORIGIN', 'DESTINATION', 'DOCUMENTATION', 'SECURITY', 'SURCHARGE', 'INLAND', 'CUSTOMS', 'OTHER')", name=op.f('ck_charge_types_charge_category')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_charge_types')),
    sa.UniqueConstraint('canonical_code', name=op.f('uq_charge_types_canonical_code'))
    )
    op.create_table('equipment_types',
    sa.Column('canonical_code', sa.String(length=50), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('transport_mode', sa.Enum('OCEAN', 'ROAD', 'AIR', 'OTHER', name='transport_mode', native_enum=False, create_constraint=False), nullable=False),
    sa.Column('supported', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("transport_mode IN ('OCEAN', 'ROAD', 'AIR', 'OTHER')", name=op.f('ck_equipment_types_transport_mode')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_equipment_types')),
    sa.UniqueConstraint('canonical_code', name=op.f('uq_equipment_types_canonical_code'))
    )
    op.create_table('locations',
    sa.Column('code', sa.String(length=100), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('city', sa.String(length=255), nullable=True),
    sa.Column('country_code', sa.String(length=2), nullable=True),
    sa.Column('location_type', sa.Enum('PORT', 'AIRPORT', 'CITY', 'WAREHOUSE', 'REGION', 'OTHER', name='location_type', native_enum=False, create_constraint=False), nullable=False),
    sa.Column('un_locode', sa.String(length=5), nullable=True),
    sa.Column('latitude', sa.Numeric(precision=10, scale=7), nullable=True),
    sa.Column('longitude', sa.Numeric(precision=10, scale=7), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("location_type IN ('PORT', 'AIRPORT', 'CITY', 'WAREHOUSE', 'REGION', 'OTHER')", name=op.f('ck_locations_location_type')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_locations'))
    )
    op.create_index(op.f('ix_locations_un_locode'), 'locations', ['un_locode'], unique=False)
    op.create_table('tenants',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.Column('default_currency', sa.String(length=3), server_default='EUR', nullable=False),
    sa.Column('timezone', sa.String(length=100), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenants')),
    sa.UniqueConstraint('slug', name=op.f('uq_tenants_slug'))
    )
    op.create_table('customers',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('external_reference', sa.String(length=255), nullable=True),
    sa.Column('default_currency', sa.String(length=3), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_customers_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customers')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_customers_tenant_id'))
    )
    op.create_index(op.f('ix_customers_tenant_id'), 'customers', ['tenant_id'], unique=False)
    op.create_table('equipment_aliases',
    sa.Column('tenant_id', sa.Uuid(), nullable=True),
    sa.Column('equipment_type_id', sa.Uuid(), nullable=False),
    sa.Column('alias', sa.String(length=255), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['equipment_type_id'], ['equipment_types.id'], name=op.f('fk_equipment_aliases_equipment_type_id_equipment_types')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_equipment_aliases_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_equipment_aliases'))
    )
    op.create_index(op.f('ix_equipment_aliases_alias'), 'equipment_aliases', ['alias'], unique=False)
    op.create_index(op.f('ix_equipment_aliases_equipment_type_id'), 'equipment_aliases', ['equipment_type_id'], unique=False)
    op.create_index(op.f('ix_equipment_aliases_tenant_id'), 'equipment_aliases', ['tenant_id'], unique=False)
    op.create_table('location_aliases',
    sa.Column('tenant_id', sa.Uuid(), nullable=True),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('alias', sa.String(length=255), nullable=False),
    sa.Column('source', sa.String(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_location_aliases_location_id_locations')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_location_aliases_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_location_aliases'))
    )
    op.create_index(op.f('ix_location_aliases_alias'), 'location_aliases', ['alias'], unique=False)
    op.create_index(op.f('ix_location_aliases_location_id'), 'location_aliases', ['location_id'], unique=False)
    op.create_index(op.f('ix_location_aliases_tenant_id'), 'location_aliases', ['tenant_id'], unique=False)
    op.create_table('location_groups',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_location_groups_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_location_groups')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_location_groups_tenant_id')),
    sa.UniqueConstraint('tenant_id', 'name', name=op.f('uq_location_groups_tenant_id'))
    )
    op.create_index(op.f('ix_location_groups_tenant_id'), 'location_groups', ['tenant_id'], unique=False)
    op.create_table('suppliers',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('supplier_type', sa.Enum('OCEAN_CARRIER', 'AIRLINE', 'TRUCKER', 'OVERSEAS_AGENT', 'NVOCC', 'OTHER', name='supplier_type', native_enum=False, create_constraint=False), nullable=False),
    sa.Column('external_reference', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("supplier_type IN ('OCEAN_CARRIER', 'AIRLINE', 'TRUCKER', 'OVERSEAS_AGENT', 'NVOCC', 'OTHER')", name=op.f('ck_suppliers_supplier_type')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_suppliers_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_suppliers')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_suppliers_tenant_id'))
    )
    op.create_index(op.f('ix_suppliers_tenant_id'), 'suppliers', ['tenant_id'], unique=False)
    op.create_table('import_profiles',
    sa.Column('supplier_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('source_type', sa.Enum('MANUAL', 'EXCEL', 'CSV', 'PDF', 'EMAIL', 'API', 'OTHER', name='source_type', native_enum=False, create_constraint=False), nullable=False),
    sa.Column('configuration_json', sa.JSON(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("source_type IN ('MANUAL', 'EXCEL', 'CSV', 'PDF', 'EMAIL', 'API', 'OTHER')", name=op.f('ck_import_profiles_source_type')),
    sa.ForeignKeyConstraint(['tenant_id', 'supplier_id'], ['suppliers.tenant_id', 'suppliers.id'], name='fk_supplier_id_suppliers_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_import_profiles_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_profiles')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_import_profiles_tenant_id'))
    )
    op.create_index(op.f('ix_import_profiles_tenant_id'), 'import_profiles', ['tenant_id'], unique=False)
    op.create_table('location_group_members',
    sa.Column('location_group_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_location_group_members_location_id_locations')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_group_id'], ['location_groups.tenant_id', 'location_groups.id'], name='fk_location_group_id_location_groups_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_location_group_members_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('location_group_id', 'location_id', name=op.f('pk_location_group_members'))
    )
    op.create_index(op.f('ix_location_group_members_tenant_id'), 'location_group_members', ['tenant_id'], unique=False)
    op.create_table('pricing_rules',
    sa.Column('customer_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('mode', sa.Enum('OCEAN_FCL', 'OCEAN_LCL', 'AIR', 'ROAD_FTL', 'ROAD_LTL', 'OTHER', name='rate_mode', native_enum=False, create_constraint=False), nullable=True),
    sa.Column('rule_type', sa.Enum('PERCENT_MARKUP', 'FIXED_MARKUP', 'MINIMUM_MARGIN', 'CHARGE_OVERRIDE', 'DISCOUNT', 'OTHER', name='rule_type', native_enum=False, create_constraint=False), nullable=False),
    sa.Column('value', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('origin_location_id', sa.Uuid(), nullable=True),
    sa.Column('origin_group_id', sa.Uuid(), nullable=True),
    sa.Column('destination_location_id', sa.Uuid(), nullable=True),
    sa.Column('destination_group_id', sa.Uuid(), nullable=True),
    sa.Column('equipment_type_id', sa.Uuid(), nullable=True),
    sa.Column('priority', sa.Integer(), server_default='0', nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=True),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("mode IN ('OCEAN_FCL', 'OCEAN_LCL', 'AIR', 'ROAD_FTL', 'ROAD_LTL', 'OTHER')", name=op.f('ck_pricing_rules_rate_mode')),
    sa.CheckConstraint("rule_type IN ('PERCENT_MARKUP', 'FIXED_MARKUP', 'MINIMUM_MARGIN', 'CHARGE_OVERRIDE', 'DISCOUNT', 'OTHER')", name=op.f('ck_pricing_rules_rule_type')),
    sa.CheckConstraint('NOT (destination_location_id IS NOT NULL AND destination_group_id IS NOT NULL)', name=op.f('ck_pricing_rules_single_destination_target')),
    sa.CheckConstraint('NOT (origin_location_id IS NOT NULL AND origin_group_id IS NOT NULL)', name=op.f('ck_pricing_rules_single_origin_target')),
    sa.CheckConstraint('valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to', name=op.f('ck_pricing_rules_validity_order')),
    sa.ForeignKeyConstraint(['destination_location_id'], ['locations.id'], name=op.f('fk_pricing_rules_destination_location_id_locations')),
    sa.ForeignKeyConstraint(['equipment_type_id'], ['equipment_types.id'], name=op.f('fk_pricing_rules_equipment_type_id_equipment_types')),
    sa.ForeignKeyConstraint(['origin_location_id'], ['locations.id'], name=op.f('fk_pricing_rules_origin_location_id_locations')),
    sa.ForeignKeyConstraint(['tenant_id', 'customer_id'], ['customers.tenant_id', 'customers.id'], name='fk_customer_id_customers_tenant'),
    sa.ForeignKeyConstraint(['tenant_id', 'destination_group_id'], ['location_groups.tenant_id', 'location_groups.id'], name='fk_destination_group_id_location_groups_tenant'),
    sa.ForeignKeyConstraint(['tenant_id', 'origin_group_id'], ['location_groups.tenant_id', 'location_groups.id'], name='fk_origin_group_id_location_groups_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_pricing_rules_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pricing_rules')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_pricing_rules_tenant_id'))
    )
    op.create_index(op.f('ix_pricing_rules_customer_id'), 'pricing_rules', ['customer_id'], unique=False)
    op.create_index(op.f('ix_pricing_rules_tenant_id'), 'pricing_rules', ['tenant_id'], unique=False)
    op.create_table('quote_requests',
    sa.Column('customer_id', sa.Uuid(), nullable=True),
    sa.Column('source_text', sa.Text(), nullable=True),
    sa.Column('mode', sa.Enum('OCEAN_FCL', 'OCEAN_LCL', 'AIR', 'ROAD_FTL', 'ROAD_LTL', 'OTHER', name='rate_mode', native_enum=False, create_constraint=False), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("mode IN ('OCEAN_FCL', 'OCEAN_LCL', 'AIR', 'ROAD_FTL', 'ROAD_LTL', 'OTHER')", name=op.f('ck_quote_requests_rate_mode')),
    sa.ForeignKeyConstraint(['tenant_id', 'customer_id'], ['customers.tenant_id', 'customers.id'], name='fk_customer_id_customers_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_quote_requests_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quote_requests')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_quote_requests_tenant_id'))
    )
    op.create_index(op.f('ix_quote_requests_tenant_id'), 'quote_requests', ['tenant_id'], unique=False)
    op.create_table('rate_sheets',
    sa.Column('supplier_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('mode', sa.Enum('OCEAN_FCL', 'OCEAN_LCL', 'AIR', 'ROAD_FTL', 'ROAD_LTL', 'OTHER', name='rate_mode', native_enum=False, create_constraint=False), nullable=False),
    sa.Column('source_type', sa.Enum('MANUAL', 'EXCEL', 'CSV', 'PDF', 'EMAIL', 'API', 'OTHER', name='source_type', native_enum=False, create_constraint=False), nullable=False),
    sa.Column('status', sa.Enum('DRAFT', 'ACTIVE', 'EXPIRED', 'ARCHIVED', name='sheet_status', native_enum=False, create_constraint=False), server_default='DRAFT', nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=True),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('parent_rate_sheet_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("mode IN ('OCEAN_FCL', 'OCEAN_LCL', 'AIR', 'ROAD_FTL', 'ROAD_LTL', 'OTHER')", name=op.f('ck_rate_sheets_rate_mode')),
    sa.CheckConstraint("source_type IN ('MANUAL', 'EXCEL', 'CSV', 'PDF', 'EMAIL', 'API', 'OTHER')", name=op.f('ck_rate_sheets_source_type')),
    sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'EXPIRED', 'ARCHIVED')", name=op.f('ck_rate_sheets_sheet_status')),
    sa.CheckConstraint('valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to', name=op.f('ck_rate_sheets_validity_order')),
    sa.CheckConstraint('version >= 1', name=op.f('ck_rate_sheets_positive_version')),
    sa.ForeignKeyConstraint(['tenant_id', 'parent_rate_sheet_id'], ['rate_sheets.tenant_id', 'rate_sheets.id'], name='fk_parent_rate_sheet_id_rate_sheets_tenant'),
    sa.ForeignKeyConstraint(['tenant_id', 'supplier_id'], ['suppliers.tenant_id', 'suppliers.id'], name='fk_supplier_id_suppliers_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_rate_sheets_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rate_sheets')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rate_sheets_tenant_id')),
    sa.UniqueConstraint('tenant_id', 'parent_rate_sheet_id', 'version', name='uq_rate_sheet_parent_version')
    )
    op.create_index(op.f('ix_rate_sheets_supplier_id'), 'rate_sheets', ['supplier_id'], unique=False)
    op.create_index(op.f('ix_rate_sheets_tenant_id'), 'rate_sheets', ['tenant_id'], unique=False)
    op.create_table('source_documents',
    sa.Column('supplier_id', sa.Uuid(), nullable=True),
    sa.Column('source_type', sa.Enum('MANUAL', 'EXCEL', 'CSV', 'PDF', 'EMAIL', 'API', 'OTHER', name='source_type', native_enum=False, create_constraint=False), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=True),
    sa.Column('checksum', sa.String(length=128), nullable=True),
    sa.Column('storage_reference', sa.Text(), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("source_type IN ('MANUAL', 'EXCEL', 'CSV', 'PDF', 'EMAIL', 'API', 'OTHER')", name=op.f('ck_source_documents_source_type')),
    sa.ForeignKeyConstraint(['tenant_id', 'supplier_id'], ['suppliers.tenant_id', 'suppliers.id'], name='fk_supplier_id_suppliers_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_source_documents_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_source_documents')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_source_documents_tenant_id'))
    )
    op.create_index(op.f('ix_source_documents_tenant_id'), 'source_documents', ['tenant_id'], unique=False)
    op.create_table('import_jobs',
    sa.Column('source_document_id', sa.Uuid(), nullable=True),
    sa.Column('import_profile_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('PENDING', 'PROCESSING', 'REVIEW_REQUIRED', 'COMPLETED', 'FAILED', name='import_status', native_enum=False, create_constraint=False), server_default='PENDING', nullable=False),
    sa.Column('rows_received', sa.Integer(), server_default='0', nullable=False),
    sa.Column('rows_imported', sa.Integer(), server_default='0', nullable=False),
    sa.Column('rows_rejected', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error_summary', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("status IN ('PENDING', 'PROCESSING', 'REVIEW_REQUIRED', 'COMPLETED', 'FAILED')", name=op.f('ck_import_jobs_import_status')),
    sa.CheckConstraint('rows_received >= 0 AND rows_imported >= 0 AND rows_rejected >= 0', name=op.f('ck_import_jobs_nonnegative_rows')),
    sa.ForeignKeyConstraint(['tenant_id', 'import_profile_id'], ['import_profiles.tenant_id', 'import_profiles.id'], name='fk_import_profile_id_import_profiles_tenant'),
    sa.ForeignKeyConstraint(['tenant_id', 'source_document_id'], ['source_documents.tenant_id', 'source_documents.id'], name='fk_source_document_id_source_documents_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_import_jobs_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_jobs')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_import_jobs_tenant_id'))
    )
    op.create_index(op.f('ix_import_jobs_tenant_id'), 'import_jobs', ['tenant_id'], unique=False)
    op.create_table('quotes',
    sa.Column('quote_request_id', sa.Uuid(), nullable=True),
    sa.Column('customer_id', sa.Uuid(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('buy_total', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('sell_total', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('margin_amount', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('margin_percent', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('status', sa.Enum('DRAFT', 'REVIEW', 'APPROVED', 'SENT', 'EXPIRED', name='quote_status', native_enum=False, create_constraint=False), server_default='DRAFT', nullable=False),
    sa.Column('valid_until', sa.Date(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("status IN ('DRAFT', 'REVIEW', 'APPROVED', 'SENT', 'EXPIRED')", name=op.f('ck_quotes_quote_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'customer_id'], ['customers.tenant_id', 'customers.id'], name='fk_customer_id_customers_tenant'),
    sa.ForeignKeyConstraint(['tenant_id', 'quote_request_id'], ['quote_requests.tenant_id', 'quote_requests.id'], name='fk_quote_request_id_quote_requests_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_quotes_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quotes')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_quotes_tenant_id'))
    )
    op.create_index(op.f('ix_quotes_tenant_id'), 'quotes', ['tenant_id'], unique=False)
    op.create_table('rates',
    sa.Column('rate_sheet_id', sa.Uuid(), nullable=False),
    sa.Column('supplier_id', sa.Uuid(), nullable=True),
    sa.Column('mode', sa.Enum('OCEAN_FCL', 'OCEAN_LCL', 'AIR', 'ROAD_FTL', 'ROAD_LTL', 'OTHER', name='rate_mode', native_enum=False, create_constraint=False), nullable=False),
    sa.Column('equipment_type_id', sa.Uuid(), nullable=True),
    sa.Column('origin_location_id', sa.Uuid(), nullable=True),
    sa.Column('origin_group_id', sa.Uuid(), nullable=True),
    sa.Column('destination_location_id', sa.Uuid(), nullable=True),
    sa.Column('destination_group_id', sa.Uuid(), nullable=True),
    sa.Column('valid_from', sa.Date(), nullable=True),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('transit_days_min', sa.Integer(), nullable=True),
    sa.Column('transit_days_max', sa.Integer(), nullable=True),
    sa.Column('service_name', sa.String(length=255), nullable=True),
    sa.Column('carrier_service_code', sa.String(length=100), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('priority', sa.Integer(), server_default='0', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('source_document_id', sa.Uuid(), nullable=True),
    sa.Column('source_reference', sa.String(length=500), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("mode IN ('OCEAN_FCL', 'OCEAN_LCL', 'AIR', 'ROAD_FTL', 'ROAD_LTL', 'OTHER')", name=op.f('ck_rates_rate_mode')),
    sa.CheckConstraint('NOT (destination_location_id IS NOT NULL AND destination_group_id IS NOT NULL)', name=op.f('ck_rates_single_destination_target')),
    sa.CheckConstraint('NOT (origin_location_id IS NOT NULL AND origin_group_id IS NOT NULL)', name=op.f('ck_rates_single_origin_target')),
    sa.CheckConstraint('transit_days_max IS NULL OR transit_days_max >= 0', name=op.f('ck_rates_nonnegative_transit_max')),
    sa.CheckConstraint('transit_days_min IS NULL OR transit_days_max IS NULL OR transit_days_min <= transit_days_max', name=op.f('ck_rates_transit_order')),
    sa.CheckConstraint('transit_days_min IS NULL OR transit_days_min >= 0', name=op.f('ck_rates_nonnegative_transit_min')),
    sa.CheckConstraint('valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to', name=op.f('ck_rates_validity_order')),
    sa.ForeignKeyConstraint(['destination_location_id'], ['locations.id'], name=op.f('fk_rates_destination_location_id_locations')),
    sa.ForeignKeyConstraint(['equipment_type_id'], ['equipment_types.id'], name=op.f('fk_rates_equipment_type_id_equipment_types')),
    sa.ForeignKeyConstraint(['origin_location_id'], ['locations.id'], name=op.f('fk_rates_origin_location_id_locations')),
    sa.ForeignKeyConstraint(['tenant_id', 'destination_group_id'], ['location_groups.tenant_id', 'location_groups.id'], name='fk_destination_group_id_location_groups_tenant'),
    sa.ForeignKeyConstraint(['tenant_id', 'origin_group_id'], ['location_groups.tenant_id', 'location_groups.id'], name='fk_origin_group_id_location_groups_tenant'),
    sa.ForeignKeyConstraint(['tenant_id', 'rate_sheet_id'], ['rate_sheets.tenant_id', 'rate_sheets.id'], name='fk_rate_sheet_id_rate_sheets_tenant'),
    sa.ForeignKeyConstraint(['tenant_id', 'source_document_id'], ['source_documents.tenant_id', 'source_documents.id'], name='fk_source_document_id_source_documents_tenant'),
    sa.ForeignKeyConstraint(['tenant_id', 'supplier_id'], ['suppliers.tenant_id', 'suppliers.id'], name='fk_supplier_id_suppliers_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_rates_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rates')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rates_tenant_id'))
    )
    op.create_index('ix_rates_destination_group', 'rates', ['tenant_id', 'mode', 'destination_group_id'], unique=False)
    op.create_index(op.f('ix_rates_destination_location_id'), 'rates', ['destination_location_id'], unique=False)
    op.create_index(op.f('ix_rates_equipment_type_id'), 'rates', ['equipment_type_id'], unique=False)
    op.create_index('ix_rates_lane', 'rates', ['tenant_id', 'mode', 'origin_location_id', 'destination_location_id', 'equipment_type_id'], unique=False)
    op.create_index('ix_rates_origin_group', 'rates', ['tenant_id', 'mode', 'origin_group_id'], unique=False)
    op.create_index(op.f('ix_rates_origin_location_id'), 'rates', ['origin_location_id'], unique=False)
    op.create_index(op.f('ix_rates_rate_sheet_id'), 'rates', ['rate_sheet_id'], unique=False)
    op.create_index(op.f('ix_rates_source_document_id'), 'rates', ['source_document_id'], unique=False)
    op.create_index('ix_rates_supplier', 'rates', ['tenant_id', 'supplier_id'], unique=False)
    op.create_index(op.f('ix_rates_tenant_id'), 'rates', ['tenant_id'], unique=False)
    op.create_index('ix_rates_validity', 'rates', ['tenant_id', 'valid_from', 'valid_to'], unique=False)
    op.create_table('rate_charges',
    sa.Column('rate_id', sa.Uuid(), nullable=False),
    sa.Column('charge_type_id', sa.Uuid(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('basis', sa.Enum('PER_CONTAINER', 'PER_SHIPMENT', 'PER_BILL', 'PER_KG', 'PER_CHARGEABLE_KG', 'PER_CBM', 'PER_PALLET', 'PER_TRIP', 'PER_KM', 'PER_MONTH', 'PERCENTAGE', 'FLAT', name='charge_basis', native_enum=False, create_constraint=False), nullable=False),
    sa.Column('minimum_amount', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('maximum_amount', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('equipment_type_id', sa.Uuid(), nullable=True),
    sa.Column('valid_from', sa.Date(), nullable=True),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('mandatory', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("basis IN ('PER_CONTAINER', 'PER_SHIPMENT', 'PER_BILL', 'PER_KG', 'PER_CHARGEABLE_KG', 'PER_CBM', 'PER_PALLET', 'PER_TRIP', 'PER_KM', 'PER_MONTH', 'PERCENTAGE', 'FLAT')", name=op.f('ck_rate_charges_charge_basis')),
    sa.CheckConstraint('minimum_amount IS NULL OR maximum_amount IS NULL OR minimum_amount <= maximum_amount', name=op.f('ck_rate_charges_amount_bounds')),
    sa.CheckConstraint('valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to', name=op.f('ck_rate_charges_validity_order')),
    sa.ForeignKeyConstraint(['charge_type_id'], ['charge_types.id'], name=op.f('fk_rate_charges_charge_type_id_charge_types')),
    sa.ForeignKeyConstraint(['equipment_type_id'], ['equipment_types.id'], name=op.f('fk_rate_charges_equipment_type_id_equipment_types')),
    sa.ForeignKeyConstraint(['tenant_id', 'rate_id'], ['rates.tenant_id', 'rates.id'], name='fk_rate_id_rates_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_rate_charges_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rate_charges')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rate_charges_tenant_id')),
    sa.UniqueConstraint('tenant_id', 'rate_id', 'id', name='uq_rate_charge_provenance')
    )
    op.create_index(op.f('ix_rate_charges_charge_type_id'), 'rate_charges', ['charge_type_id'], unique=False)
    op.create_index(op.f('ix_rate_charges_rate_id'), 'rate_charges', ['rate_id'], unique=False)
    op.create_index(op.f('ix_rate_charges_tenant_id'), 'rate_charges', ['tenant_id'], unique=False)
    op.create_table('quote_lines',
    sa.Column('quote_id', sa.Uuid(), nullable=False),
    sa.Column('rate_id', sa.Uuid(), nullable=True),
    sa.Column('rate_charge_id', sa.Uuid(), nullable=True),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('unit_amount', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('total_amount', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('basis', sa.String(length=100), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('rate_charge_id IS NULL OR rate_id IS NOT NULL', name=op.f('ck_quote_lines_charge_requires_rate')),
    sa.ForeignKeyConstraint(['tenant_id', 'quote_id'], ['quotes.tenant_id', 'quotes.id'], name='fk_quote_id_quotes_tenant'),
    sa.ForeignKeyConstraint(['tenant_id', 'rate_charge_id'], ['rate_charges.tenant_id', 'rate_charges.id'], name='fk_rate_charge_id_rate_charges_tenant'),
    sa.ForeignKeyConstraint(['tenant_id', 'rate_id', 'rate_charge_id'], ['rate_charges.tenant_id', 'rate_charges.rate_id', 'rate_charges.id'], name='fk_quote_line_rate_charge_provenance'),
    sa.ForeignKeyConstraint(['tenant_id', 'rate_id'], ['rates.tenant_id', 'rates.id'], name='fk_rate_id_rates_tenant'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_quote_lines_tenant_id_tenants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quote_lines')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_quote_lines_tenant_id'))
    )
    op.create_index(op.f('ix_quote_lines_quote_id'), 'quote_lines', ['quote_id'], unique=False)
    op.create_index(op.f('ix_quote_lines_tenant_id'), 'quote_lines', ['tenant_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_quote_lines_tenant_id'), table_name='quote_lines')
    op.drop_index(op.f('ix_quote_lines_quote_id'), table_name='quote_lines')
    op.drop_table('quote_lines')
    op.drop_index(op.f('ix_rate_charges_tenant_id'), table_name='rate_charges')
    op.drop_index(op.f('ix_rate_charges_rate_id'), table_name='rate_charges')
    op.drop_index(op.f('ix_rate_charges_charge_type_id'), table_name='rate_charges')
    op.drop_table('rate_charges')
    op.drop_index('ix_rates_validity', table_name='rates')
    op.drop_index(op.f('ix_rates_tenant_id'), table_name='rates')
    op.drop_index('ix_rates_supplier', table_name='rates')
    op.drop_index(op.f('ix_rates_source_document_id'), table_name='rates')
    op.drop_index(op.f('ix_rates_rate_sheet_id'), table_name='rates')
    op.drop_index(op.f('ix_rates_origin_location_id'), table_name='rates')
    op.drop_index('ix_rates_origin_group', table_name='rates')
    op.drop_index('ix_rates_lane', table_name='rates')
    op.drop_index(op.f('ix_rates_equipment_type_id'), table_name='rates')
    op.drop_index(op.f('ix_rates_destination_location_id'), table_name='rates')
    op.drop_index('ix_rates_destination_group', table_name='rates')
    op.drop_table('rates')
    op.drop_index(op.f('ix_quotes_tenant_id'), table_name='quotes')
    op.drop_table('quotes')
    op.drop_index(op.f('ix_import_jobs_tenant_id'), table_name='import_jobs')
    op.drop_table('import_jobs')
    op.drop_index(op.f('ix_source_documents_tenant_id'), table_name='source_documents')
    op.drop_table('source_documents')
    op.drop_index(op.f('ix_rate_sheets_tenant_id'), table_name='rate_sheets')
    op.drop_index(op.f('ix_rate_sheets_supplier_id'), table_name='rate_sheets')
    op.drop_table('rate_sheets')
    op.drop_index(op.f('ix_quote_requests_tenant_id'), table_name='quote_requests')
    op.drop_table('quote_requests')
    op.drop_index(op.f('ix_pricing_rules_tenant_id'), table_name='pricing_rules')
    op.drop_index(op.f('ix_pricing_rules_customer_id'), table_name='pricing_rules')
    op.drop_table('pricing_rules')
    op.drop_index(op.f('ix_location_group_members_tenant_id'), table_name='location_group_members')
    op.drop_table('location_group_members')
    op.drop_index(op.f('ix_import_profiles_tenant_id'), table_name='import_profiles')
    op.drop_table('import_profiles')
    op.drop_index(op.f('ix_suppliers_tenant_id'), table_name='suppliers')
    op.drop_table('suppliers')
    op.drop_index(op.f('ix_location_groups_tenant_id'), table_name='location_groups')
    op.drop_table('location_groups')
    op.drop_index(op.f('ix_location_aliases_tenant_id'), table_name='location_aliases')
    op.drop_index(op.f('ix_location_aliases_location_id'), table_name='location_aliases')
    op.drop_index(op.f('ix_location_aliases_alias'), table_name='location_aliases')
    op.drop_table('location_aliases')
    op.drop_index(op.f('ix_equipment_aliases_tenant_id'), table_name='equipment_aliases')
    op.drop_index(op.f('ix_equipment_aliases_equipment_type_id'), table_name='equipment_aliases')
    op.drop_index(op.f('ix_equipment_aliases_alias'), table_name='equipment_aliases')
    op.drop_table('equipment_aliases')
    op.drop_index(op.f('ix_customers_tenant_id'), table_name='customers')
    op.drop_table('customers')
    op.drop_table('tenants')
    op.drop_index(op.f('ix_locations_un_locode'), table_name='locations')
    op.drop_table('locations')
    op.drop_table('equipment_types')
    op.drop_table('charge_types')
