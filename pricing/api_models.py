from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pricing.models import PricingRequest
from pricing.exceptions import InvalidPricingRequest
from pricing.resolvers import resolve_equipment, resolve_location


class StructuredSpotRFQ(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    container_type: str = Field(min_length=1)
    container_count: int = Field(gt=0, strict=True)
    raw_equipment: str | None = None
    gross_weight_kg: Decimal | None = Field(default=None, ge=0)
    commodity: str | None = None
    cargo_ready_date: date | None = None
    required_arrival_date: date | None = None
    incoterm: str | None = None
    dangerous_goods: bool | None = Field(default=None, strict=True)
    hs_code: str | None = None
    service_scope: str | None = None
    unsupported_equipment: bool = Field(default=False, strict=True)


class SpotQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID | None = None
    customer_id: UUID | None = None
    mode: Literal["OCEAN_FCL"] = "OCEAN_FCL"
    rfq: StructuredSpotRFQ | None = None
    origin_location_id: UUID | None = None
    destination_location_id: UUID | None = None
    equipment_type_id: UUID | None = None
    container_count: int | None = Field(default=None, gt=0, strict=True)
    dangerous_goods: bool | None = Field(default=None, strict=True)
    incoterm: str | None = None
    effective_date: date
    requested_currency: str
    persist: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def validate_shipment(self):
        ids = (self.origin_location_id, self.destination_location_id, self.equipment_type_id, self.container_count)
        if self.rfq is not None:
            if any(value is not None for value in ids) or self.dangerous_goods is not None or self.incoterm is not None:
                raise ValueError("Supply either rfq or reviewed shipment fields, not both")
        elif any(value is None for value in ids):
            raise ValueError("Origin, destination, equipment and positive whole-number quantity are required")
        dg = self.rfq.dangerous_goods if self.rfq else self.dangerous_goods
        if dg is None:
            raise ValueError("Dangerous-goods status is unknown; confirm before pricing")
        return self

    def to_pricing_request(self, session, tenant_id=None):
        tenant_id = tenant_id or self.tenant_id
        if self.rfq is None:
            return PricingRequest(tenant_id=tenant_id, customer_id=self.customer_id, mode=self.mode,
                origin_location_id=self.origin_location_id, destination_location_id=self.destination_location_id,
                equipment_type_id=self.equipment_type_id, container_count=self.container_count,
                effective_date=self.effective_date, requested_currency=self.requested_currency,
                dangerous_goods=self.dangerous_goods, incoterm=self.incoterm)
        if self.rfq.unsupported_equipment:
            raise InvalidPricingRequest("RFQ identifies unsupported equipment")
        origin = resolve_location(session, tenant_id, self.rfq.origin)
        destination = resolve_location(session, tenant_id, self.rfq.destination)
        equipment = resolve_equipment(session, tenant_id, self.rfq.container_type)
        return PricingRequest(tenant_id=tenant_id, customer_id=self.customer_id, mode=self.mode,
            origin_location_id=origin.id, destination_location_id=destination.id, equipment_type_id=equipment.id,
            container_count=self.rfq.container_count, effective_date=self.effective_date,
            requested_currency=self.requested_currency, dangerous_goods=self.rfq.dangerous_goods, incoterm=self.rfq.incoterm)
