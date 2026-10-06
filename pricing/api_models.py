from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
    tenant_id: UUID
    customer_id: UUID | None = None
    mode: Literal["OCEAN_FCL"] = "OCEAN_FCL"
    rfq: StructuredSpotRFQ
    effective_date: date
    requested_currency: str
    persist: bool = Field(default=False, strict=True)

    def to_pricing_request(self, session):
        if self.rfq.unsupported_equipment:
            raise InvalidPricingRequest("RFQ identifies unsupported equipment")
        origin = resolve_location(session, self.tenant_id, self.rfq.origin)
        destination = resolve_location(session, self.tenant_id, self.rfq.destination)
        equipment = resolve_equipment(session, self.tenant_id, self.rfq.container_type)
        return PricingRequest(tenant_id=self.tenant_id, customer_id=self.customer_id, mode=self.mode,
            origin_location_id=origin.id, destination_location_id=destination.id, equipment_type_id=equipment.id,
            container_count=self.rfq.container_count, effective_date=self.effective_date,
            requested_currency=self.requested_currency, dangerous_goods=self.rfq.dangerous_goods, incoterm=self.rfq.incoterm)
