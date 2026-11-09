"""Carrier sourcing phase 1: structured quote requests, carrier contacts, lane capabilities, RFQ drafts.

Revision ID: 0005_sourcing
Revises: 0004_management
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_sourcing"
down_revision = "0004_management"
branch_labels = None
depends_on = None

SOURCING_STATUSES = ("NONE", "NO_CARRIER_AVAILABLE", "RFQ_DRAFTED", "AWAITING_REPLIES", "RATE_RECEIVED", "CANCELLED")
RFQ_STATUSES = ("DRAFT", "APPROVED", "SENT", "REPLIED", "CANCELLED", "CLOSED")
RATE_MODES = ("OCEAN_FCL", "OCEAN_LCL", "AIR", "ROAD_FTL", "ROAD_LTL", "OTHER")


def _enum(name, values):
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=False)


def _in(column, values):
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _timestamps():
    return (sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def _single_target(table, side):
    present = " + ".join(f"(CASE WHEN {side}_{column} IS NOT NULL THEN 1 ELSE 0 END)"
                         for column in ("location_id", "group_id", "country_code"))
    return sa.CheckConstraint(f"{present} = 1", name=op.f(f"ck_{table}_single_{side}_target"))


def _recreate():
    # SQLite cannot ALTER-add foreign keys, checks or non-constant defaults; rebuild the table there.
    return "always" if op.get_context().dialect.name == "sqlite" else "auto"


def upgrade():
    with op.batch_alter_table("quote_requests", recreate=_recreate()) as batch:
        batch.add_column(sa.Column("origin_location_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("destination_location_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("equipment_type_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("container_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("effective_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("requested_currency", sa.String(3), nullable=True))
        batch.add_column(sa.Column("dangerous_goods", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("incoterm", sa.String(50), nullable=True))
        batch.add_column(sa.Column("commodity", sa.String(255), nullable=True))
        batch.add_column(sa.Column("gross_weight_kg", sa.Numeric(18, 3), nullable=True))
        batch.add_column(sa.Column("sourcing_status", _enum("sourcing_status", SOURCING_STATUSES),
                                   nullable=False, server_default="NONE"))
        batch.add_column(sa.Column("request_fingerprint", sa.String(64), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
        batch.create_foreign_key("fk_quote_requests_origin_location_id_locations", "locations", ["origin_location_id"], ["id"])
        batch.create_foreign_key("fk_quote_requests_destination_location_id_locations", "locations",
                                 ["destination_location_id"], ["id"])
        batch.create_foreign_key("fk_quote_requests_equipment_type_id_equipment_types", "equipment_types",
                                 ["equipment_type_id"], ["id"])
        batch.create_check_constraint(op.f("ck_quote_requests_positive_container_count"),
                                      "container_count IS NULL OR container_count > 0")
        batch.create_check_constraint(op.f("ck_quote_requests_positive_gross_weight"),
                                      "gross_weight_kg IS NULL OR gross_weight_kg > 0")
        batch.create_check_constraint(op.f("ck_quote_requests_sourcing_status"), _in("sourcing_status", SOURCING_STATUSES))
        batch.create_index("ix_quote_requests_fingerprint", ["tenant_id", "request_fingerprint"])
    # Legacy rows keep their creation time as last update.
    op.execute(sa.text("UPDATE quote_requests SET updated_at = created_at"))

    op.create_table("supplier_contacts",
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("is_rfq_recipient", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_supplier_contacts"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supplier_contacts_tenant_id"),
        sa.UniqueConstraint("tenant_id", "supplier_id", "email", name="uq_supplier_contacts_supplier_email"),
        sa.UniqueConstraint("tenant_id", "supplier_id", "id", name="uq_supplier_contacts_provenance"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_supplier_contacts_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.id"],
                                name="fk_supplier_id_suppliers_tenant"))
    op.create_index("ix_supplier_contacts_tenant_id", "supplier_contacts", ["tenant_id"])
    op.create_index("ix_supplier_contacts_supplier_id", "supplier_contacts", ["supplier_id"])
    op.create_index("ix_supplier_contacts_email", "supplier_contacts", ["tenant_id", "email"])

    op.create_table("supplier_lane_capabilities",
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("mode", _enum("rate_mode", RATE_MODES), nullable=False),
        sa.Column("origin_location_id", sa.Uuid(), nullable=True),
        sa.Column("origin_group_id", sa.Uuid(), nullable=True),
        sa.Column("origin_country_code", sa.String(2), nullable=True),
        sa.Column("destination_location_id", sa.Uuid(), nullable=True),
        sa.Column("destination_group_id", sa.Uuid(), nullable=True),
        sa.Column("destination_country_code", sa.String(2), nullable=True),
        sa.Column("equipment_type_id", sa.Uuid(), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_supplier_lane_capabilities"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supplier_lane_capabilities_tenant_id"),
        sa.CheckConstraint(_in("mode", RATE_MODES), name=op.f("ck_supplier_lane_capabilities_rate_mode")),
        _single_target("supplier_lane_capabilities", "origin"),
        _single_target("supplier_lane_capabilities", "destination"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_supplier_lane_capabilities_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.id"],
                                name="fk_supplier_id_suppliers_tenant"),
        sa.ForeignKeyConstraint(["tenant_id", "origin_group_id"], ["location_groups.tenant_id", "location_groups.id"],
                                name="fk_origin_group_id_location_groups_tenant"),
        sa.ForeignKeyConstraint(["tenant_id", "destination_group_id"],
                                ["location_groups.tenant_id", "location_groups.id"],
                                name="fk_destination_group_id_location_groups_tenant"),
        sa.ForeignKeyConstraint(["origin_location_id"], ["locations.id"],
                                name="fk_supplier_lane_capabilities_origin_location_id_locations"),
        sa.ForeignKeyConstraint(["destination_location_id"], ["locations.id"],
                                name="fk_supplier_lane_capabilities_destination_location_id_locations"),
        sa.ForeignKeyConstraint(["equipment_type_id"], ["equipment_types.id"],
                                name="fk_supplier_lane_capabilities_equipment_type_id_equipment_types"))
    op.create_index("ix_supplier_lane_capabilities_tenant_id", "supplier_lane_capabilities", ["tenant_id"])
    op.create_index("ix_supplier_lane_capabilities_supplier_id", "supplier_lane_capabilities", ["supplier_id"])
    op.create_index("ix_supplier_lane_capabilities_lookup", "supplier_lane_capabilities",
                    ["tenant_id", "mode", "is_active"])

    op.create_table("carrier_rfqs",
        sa.Column("quote_request_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_contact_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("reference_code", sa.String(16), nullable=False),
        sa.Column("outbound_message_id", sa.String(255), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("template_version", sa.String(50), nullable=False),
        sa.Column("status", _enum("rfq_status", RFQ_STATUSES), server_default="DRAFT", nullable=False),
        sa.Column("send_channel", sa.String(50), nullable=True),
        sa.Column("response_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("selection_metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_carrier_rfqs"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_carrier_rfqs_tenant_id"),
        sa.UniqueConstraint("tenant_id", "reference_code", name="uq_carrier_rfqs_reference_code"),
        sa.UniqueConstraint("tenant_id", "outbound_message_id", name="uq_carrier_rfqs_outbound_message_id"),
        sa.UniqueConstraint("tenant_id", "quote_request_id", "supplier_contact_id", name="uq_carrier_rfqs_request_contact"),
        sa.CheckConstraint(_in("status", RFQ_STATUSES), name=op.f("ck_carrier_rfqs_rfq_status")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_carrier_rfqs_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["tenant_id", "quote_request_id"], ["quote_requests.tenant_id", "quote_requests.id"],
                                name="fk_quote_request_id_quote_requests_tenant"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.id"],
                                name="fk_supplier_id_suppliers_tenant"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_contact_id"],
                                ["supplier_contacts.tenant_id", "supplier_contacts.id"],
                                name="fk_supplier_contact_id_supplier_contacts_tenant"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_id", "supplier_contact_id"],
                                ["supplier_contacts.tenant_id", "supplier_contacts.supplier_id", "supplier_contacts.id"],
                                name="fk_carrier_rfq_contact_provenance"))
    op.create_index("ix_carrier_rfqs_tenant_id", "carrier_rfqs", ["tenant_id"])
    op.create_index("ix_carrier_rfqs_quote_request_id", "carrier_rfqs", ["quote_request_id"])
    op.create_index("ix_carrier_rfqs_supplier_id", "carrier_rfqs", ["supplier_id"])
    op.create_index("ix_carrier_rfqs_status", "carrier_rfqs", ["tenant_id", "status"])


def downgrade():
    # Do not silently discard the RFQ audit trail (mirrors 0003/0004).
    if not op.get_context().as_sql:
        bind = op.get_bind()
        if bind.scalar(sa.text("SELECT COUNT(*) FROM carrier_rfqs")):
            raise RuntimeError("Cannot discard carrier RFQ history; export it explicitly before downgrade")
        if bind.scalar(sa.text("SELECT COUNT(*) FROM quote_requests WHERE sourcing_status <> 'NONE' "
                               "OR request_fingerprint IS NOT NULL")):
            raise RuntimeError("Cannot discard structured sourcing requests; export them explicitly before downgrade")
    op.drop_table("carrier_rfqs")
    op.drop_table("supplier_lane_capabilities")
    op.drop_table("supplier_contacts")
    with op.batch_alter_table("quote_requests", recreate=_recreate()) as batch:
        batch.drop_index("ix_quote_requests_fingerprint")
        batch.drop_constraint(op.f("ck_quote_requests_sourcing_status"), type_="check")
        batch.drop_constraint(op.f("ck_quote_requests_positive_gross_weight"), type_="check")
        batch.drop_constraint(op.f("ck_quote_requests_positive_container_count"), type_="check")
        batch.drop_constraint("fk_quote_requests_equipment_type_id_equipment_types", type_="foreignkey")
        batch.drop_constraint("fk_quote_requests_destination_location_id_locations", type_="foreignkey")
        batch.drop_constraint("fk_quote_requests_origin_location_id_locations", type_="foreignkey")
        for column in ("updated_at", "request_fingerprint", "sourcing_status", "gross_weight_kg", "commodity",
                       "incoterm", "dangerous_goods", "requested_currency", "effective_date", "container_count",
                       "equipment_type_id", "destination_location_id", "origin_location_id"):
            batch.drop_column(column)
