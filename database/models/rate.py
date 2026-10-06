from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, Uuid, true
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, UUIDPrimaryKey, TenantOwned, Timestamps, owned, tenant_fk
from database.models.enums import RATE_MODE, SOURCE_TYPE, SHEET_STATUS, CHARGE_CATEGORY, CHARGE_BASIS, SUPPLIER_COMMERCIAL_TYPE, enumeration


def targeting_checks():
    return (
        CheckConstraint("NOT (origin_location_id IS NOT NULL AND origin_group_id IS NOT NULL)", name="single_origin_target"),
        CheckConstraint("NOT (destination_location_id IS NOT NULL AND destination_group_id IS NOT NULL)", name="single_destination_target"),
    )


def validity_check():
    return CheckConstraint("valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to", name="validity_order")


class RateSheet(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "rate_sheets"
    __table_args__ = (*owned(), tenant_fk("supplier_id", "suppliers"),
                      tenant_fk("parent_rate_sheet_id", "rate_sheets"),
                      UniqueConstraint("tenant_id", "parent_rate_sheet_id", "version", name="uq_rate_sheet_parent_version"),
                      CheckConstraint("version >= 1", name="positive_version"), validity_check())
    supplier_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(255))
    mode: Mapped[str] = mapped_column(RATE_MODE)
    source_type: Mapped[str] = mapped_column(SOURCE_TYPE)
    status: Mapped[str] = mapped_column(SHEET_STATUS, default="DRAFT", server_default="DRAFT")
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    parent_rate_sheet_id: Mapped[UUID | None] = mapped_column(Uuid)
    commercial_type: Mapped[str] = mapped_column(SUPPLIER_COMMERCIAL_TYPE, default="SPOT", server_default="SPOT")
    notes: Mapped[str | None] = mapped_column(Text)


class Rate(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "rates"
    __table_args__ = (*owned(), tenant_fk("rate_sheet_id", "rate_sheets"),
                      tenant_fk("supplier_id", "suppliers"), tenant_fk("origin_group_id", "location_groups"),
                      tenant_fk("destination_group_id", "location_groups"), tenant_fk("source_document_id", "source_documents"),
                      *targeting_checks(), validity_check(),
                      CheckConstraint("transit_days_min IS NULL OR transit_days_min >= 0", name="nonnegative_transit_min"),
                      CheckConstraint("transit_days_max IS NULL OR transit_days_max >= 0", name="nonnegative_transit_max"),
                      CheckConstraint("transit_days_min IS NULL OR transit_days_max IS NULL OR transit_days_min <= transit_days_max", name="transit_order"),
                      Index("ix_rates_lane", "tenant_id", "mode", "origin_location_id", "destination_location_id", "equipment_type_id"),
                      Index("ix_rates_origin_group", "tenant_id", "mode", "origin_group_id"),
                      Index("ix_rates_destination_group", "tenant_id", "mode", "destination_group_id"),
                      Index("ix_rates_validity", "tenant_id", "valid_from", "valid_to"),
                      Index("ix_rates_supplier", "tenant_id", "supplier_id"))
    rate_sheet_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    # Supplier buy rates only; CUSTOMER_FIXED is a customer-facing Quote.
    commercial_type: Mapped[str] = mapped_column(SUPPLIER_COMMERCIAL_TYPE, default="SPOT", server_default="SPOT")
    supplier_id: Mapped[UUID | None] = mapped_column(Uuid)
    mode: Mapped[str] = mapped_column(RATE_MODE)
    equipment_type_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("equipment_types.id"), index=True)
    origin_location_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    origin_group_id: Mapped[UUID | None] = mapped_column(Uuid)
    destination_location_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    destination_group_id: Mapped[UUID | None] = mapped_column(Uuid)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    transit_days_min: Mapped[int | None] = mapped_column(Integer)
    transit_days_max: Mapped[int | None] = mapped_column(Integer)
    service_name: Mapped[str | None] = mapped_column(String(255))
    carrier_service_code: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    market_notes: Mapped[str | None] = mapped_column(Text)
    capacity_notes: Mapped[str | None] = mapped_column(Text)
    service_frequency_notes: Mapped[str | None] = mapped_column(Text)
    disruption_notes: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    status: Mapped[str] = mapped_column(SHEET_STATUS, default="ACTIVE", server_default="ACTIVE")
    source_document_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    source_reference: Mapped[str | None] = mapped_column(String(500))


class ChargeType(UUIDPrimaryKey, Base):
    __tablename__ = "charge_types"
    canonical_code: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(CHARGE_CATEGORY)


class RateCharge(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "rate_charges"
    __table_args__ = (*owned(), UniqueConstraint("tenant_id", "rate_id", "id", name="uq_rate_charge_provenance"),
                      tenant_fk("rate_id", "rates"), validity_check(),
                      CheckConstraint("minimum_amount IS NULL OR maximum_amount IS NULL OR minimum_amount <= maximum_amount", name="amount_bounds"))
    rate_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    charge_type_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("charge_types.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    currency: Mapped[str] = mapped_column(String(3))
    basis: Mapped[str] = mapped_column(CHARGE_BASIS)
    percentage_base: Mapped[str | None] = mapped_column(enumeration("percentage_base", "FREIGHT_SUBTOTAL", "BUY_SUBTOTAL"))
    minimum_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    maximum_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    equipment_type_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("equipment_types.id"))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    notes: Mapped[str | None] = mapped_column(Text)
