from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PricingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: UUID
    customer_id: UUID | None = None
    mode: Literal["OCEAN_FCL"] = "OCEAN_FCL"
    origin_location_id: UUID
    destination_location_id: UUID
    equipment_type_id: UUID
    container_count: int = Field(gt=0, strict=True)
    effective_date: date
    requested_currency: str = Field(pattern=r"^[A-Z]{3}$")
    dangerous_goods: bool | None = Field(default=None, strict=True)
    incoterm: str | None = None

    @field_validator("requested_currency", mode="before")
    @classmethod
    def normalize_currency(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class QuoteLineResult(BaseModel):
    rate_charge_id: UUID
    charge_type: str
    category: str
    source_amount: Decimal
    source_currency: str
    source_total_amount: Decimal
    quantity: Decimal
    basis: str
    percentage_base: str | None = None
    percentage_base_subtotal: Decimal | None = None
    converted_unit_amount: Decimal
    converted_total: Decimal
    calculation_unit_amount: Decimal
    calculation_total: Decimal
    quote_currency: str
    fx_rate_id: UUID | None = None
    fx_rate_value: Decimal


class QuoteResult(BaseModel):
    tenant_id: UUID
    customer_id: UUID | None
    selected_rate_id: UUID | None = None
    supplier_id: UUID | None = None
    quote_id: UUID | None = None
    equipment: str
    container_count: int
    origin: str
    destination: str
    effective_date: date
    currency: str
    buy_total: Decimal | None = None
    markup_amount: Decimal | None = None
    discount_amount: Decimal | None = None
    final_margin_amount: Decimal | None = None
    margin_percent: Decimal | None = None
    sell_total: Decimal | None = None
    line_items: list[QuoteLineResult] = Field(default_factory=list)
    applied_pricing_rules: list[dict] = Field(default_factory=list)
    fx_conversions: list[dict] = Field(default_factory=list)
    optional_charges_available: list[dict] = Field(default_factory=list)
    rate_selection_metadata: dict = Field(default_factory=dict)
    status: Literal["PRICED", "NO_RATE_FOUND", "MISSING_FX", "AMBIGUOUS_RATE", "AMBIGUOUS_PRICING_RULE"]
    error: str | None = None
    error_metadata: dict = Field(default_factory=dict)
