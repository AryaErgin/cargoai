from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["DRAFT", "ACTIVE", "EXPIRED", "ARCHIVED"]
CommercialType = Literal["SPOT", "CONTRACT"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TenantRequest(StrictModel):
    tenant_id: UUID


class SheetCreate(TenantRequest):
    supplier_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    mode: Literal["OCEAN_FCL"] = "OCEAN_FCL"
    source_type: Literal["MANUAL"] = "MANUAL"
    commercial_type: CommercialType = "SPOT"
    valid_from: date | None = None
    valid_to: date | None = None
    currency: str | None = None
    version: Literal[1] = 1
    notes: str | None = None


class ChargeCreate(StrictModel):
    charge_type: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    currency: str
    basis: Literal["PER_CONTAINER", "PER_SHIPMENT", "FLAT", "PERCENTAGE"]
    percentage_base: Literal["FREIGHT_SUBTOTAL", "BUY_SUBTOTAL"] | None = None
    minimum_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    maximum_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    equipment_type_id: UUID | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    mandatory: bool = True
    notes: str | None = None

    @field_validator("amount", "minimum_amount", "maximum_amount", mode="before")
    @classmethod
    def no_floats(cls, value):
        if isinstance(value, float):
            raise ValueError("Use decimal strings for monetary values")
        return value


class ChargeRequest(ChargeCreate):
    tenant_id: UUID


class RateCreate(TenantRequest):
    rate_sheet_id: UUID
    supplier_id: UUID | None = None
    mode: Literal["OCEAN_FCL"] = "OCEAN_FCL"
    equipment_type_id: UUID
    origin_location_id: UUID | None = None
    origin_group_id: UUID | None = None
    destination_location_id: UUID | None = None
    destination_group_id: UUID | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    priority: int = 0
    service_name: str | None = Field(default=None, max_length=255)
    carrier_service_code: str | None = Field(default=None, max_length=100)
    commercial_type: CommercialType = "SPOT"
    market_notes: str | None = None
    capacity_notes: str | None = None
    service_frequency_notes: str | None = None
    disruption_notes: str | None = None
    notes: str | None = None
    status: Status = "DRAFT"
    source_reference: str | None = Field(default=None, max_length=500)
    charges: list[ChargeCreate] = Field(default_factory=list)


class RateChanges(StrictModel):
    supplier_id: UUID | None = None
    equipment_type_id: UUID | None = None
    origin_location_id: UUID | None = None
    origin_group_id: UUID | None = None
    destination_location_id: UUID | None = None
    destination_group_id: UUID | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    priority: int | None = None
    service_name: str | None = Field(default=None, max_length=255)
    carrier_service_code: str | None = Field(default=None, max_length=100)
    commercial_type: CommercialType | None = None
    market_notes: str | None = None
    capacity_notes: str | None = None
    service_frequency_notes: str | None = None
    disruption_notes: str | None = None
    notes: str | None = None
    status: Status | None = None
    source_reference: str | None = Field(default=None, max_length=500)


class RatePatch(TenantRequest):
    changes: RateChanges


class RateVersion(RatePatch):
    charge_changes: dict[UUID, dict] = Field(default_factory=dict)
    additional_charges: list[ChargeCreate] = Field(default_factory=list)


class DeactivateRequest(TenantRequest):
    status: Literal["EXPIRED", "ARCHIVED"] = "ARCHIVED"
