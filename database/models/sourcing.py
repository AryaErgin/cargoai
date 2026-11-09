"""Carrier sourcing: carrier contacts, lane capabilities and RFQ drafts (phase 1).

Carriers are existing `Supplier` rows. Every business reference is a composite
tenant FK so a cross-tenant link is impossible at the database level.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import (Boolean, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, String,
                        Text, UniqueConstraint, Uuid, true)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, UUIDPrimaryKey, TenantOwned, Timestamps, UTCDateTime, owned, tenant_fk
from database.models.enums import RATE_MODE, RFQ_STATUS


def _single_target(side):
    present = " + ".join(f"(CASE WHEN {side}_{column} IS NOT NULL THEN 1 ELSE 0 END)"
                         for column in ("location_id", "group_id", "country_code"))
    return CheckConstraint(f"{present} = 1", name=f"single_{side}_target")


class SupplierContact(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "supplier_contacts"
    __table_args__ = (*owned(), tenant_fk("supplier_id", "suppliers"),
                      UniqueConstraint("tenant_id", "supplier_id", "email", name="uq_supplier_contacts_supplier_email"),
                      UniqueConstraint("tenant_id", "supplier_id", "id", name="uq_supplier_contacts_provenance"),
                      Index("ix_supplier_contacts_email", "tenant_id", "email"))
    supplier_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    is_rfq_recipient: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class SupplierLaneCapability(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    """Directional lane a carrier is willing to quote; exactly one target per side."""
    __tablename__ = "supplier_lane_capabilities"
    __table_args__ = (*owned(), tenant_fk("supplier_id", "suppliers"),
                      tenant_fk("origin_group_id", "location_groups"),
                      tenant_fk("destination_group_id", "location_groups"),
                      _single_target("origin"), _single_target("destination"),
                      Index("ix_supplier_lane_capabilities_lookup", "tenant_id", "mode", "is_active"))
    supplier_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    mode: Mapped[str] = mapped_column(RATE_MODE)
    origin_location_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("locations.id"))
    origin_group_id: Mapped[UUID | None] = mapped_column(Uuid)
    origin_country_code: Mapped[str | None] = mapped_column(String(2))
    destination_location_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("locations.id"))
    destination_group_id: Mapped[UUID | None] = mapped_column(Uuid)
    destination_country_code: Mapped[str | None] = mapped_column(String(2))
    # NULL means any supported equipment.
    equipment_type_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("equipment_types.id"))
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    notes: Mapped[str | None] = mapped_column(Text)


class CarrierRFQ(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    """One reviewable RFQ draft per selected carrier contact. Nothing is sent automatically."""
    __tablename__ = "carrier_rfqs"
    __table_args__ = (*owned(), tenant_fk("quote_request_id", "quote_requests"),
                      tenant_fk("supplier_id", "suppliers"), tenant_fk("supplier_contact_id", "supplier_contacts"),
                      # The contact must belong to the RFQ's supplier, not merely to the tenant.
                      ForeignKeyConstraint(["tenant_id", "supplier_id", "supplier_contact_id"],
                                           ["supplier_contacts.tenant_id", "supplier_contacts.supplier_id",
                                            "supplier_contacts.id"], name="fk_carrier_rfq_contact_provenance"),
                      UniqueConstraint("tenant_id", "reference_code", name="uq_carrier_rfqs_reference_code"),
                      UniqueConstraint("tenant_id", "outbound_message_id", name="uq_carrier_rfqs_outbound_message_id"),
                      UniqueConstraint("tenant_id", "quote_request_id", "supplier_contact_id",
                                       name="uq_carrier_rfqs_request_contact"),
                      Index("ix_carrier_rfqs_status", "tenant_id", "status"))
    quote_request_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    supplier_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    supplier_contact_id: Mapped[UUID] = mapped_column(Uuid)
    recipient_email: Mapped[str] = mapped_column(String(320))
    reference_code: Mapped[str] = mapped_column(String(16))
    outbound_message_id: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    template_version: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(RFQ_STATUS, default="DRAFT", server_default="DRAFT")
    send_channel: Mapped[str | None] = mapped_column(String(50))
    response_due_at: Mapped[datetime] = mapped_column(UTCDateTime())
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # Internal audit of why this carrier was chosen; never exposed to customer routes.
    selection_metadata: Mapped[dict] = mapped_column(JSON)
