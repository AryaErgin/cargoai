"""Sourcing request/command models. Extra fields are forbidden; money/weights are never floats."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sourcing.rfq_template import single_line

_WEIGHT = re.compile(r"^[0-9]{1,15}(\.[0-9]{1,3})?$")


class StartSourcing(BaseModel):
    """Reviewed shipment fields. Tenant comes only from access control, never from the body."""
    model_config = ConfigDict(extra="forbid")
    origin_location_id: UUID
    destination_location_id: UUID
    equipment_type_id: UUID
    container_count: int = Field(gt=0, strict=True)
    effective_date: date
    requested_currency: str = Field(pattern=r"^[A-Z]{3}$")
    dangerous_goods: bool = Field(strict=True)
    incoterm: str | None = Field(default=None, max_length=50)
    customer_id: UUID | None = None
    commodity: str | None = Field(default=None, max_length=255)
    gross_weight_kg: Decimal | None = None

    @field_validator("requested_currency", mode="before")
    @classmethod
    def normalize_currency(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("incoterm", mode="before")
    @classmethod
    def normalize_incoterm(cls, value):
        value = single_line(value) if isinstance(value, str) else value
        return value.upper() if isinstance(value, str) else value

    @field_validator("commodity", mode="before")
    @classmethod
    def normalize_commodity(cls, value):
        return single_line(value) if isinstance(value, str) else value

    @field_validator("gross_weight_kg", mode="before")
    @classmethod
    def decimal_string_weight(cls, value):
        if value is None or isinstance(value, Decimal):
            parsed = value
        elif isinstance(value, str) and _WEIGHT.fullmatch(value.strip()):
            try:
                parsed = Decimal(value.strip())
            except InvalidOperation:
                raise ValueError("gross_weight_kg must be a decimal string") from None
        else:
            raise ValueError("gross_weight_kg must be a decimal string with at most 3 decimals")
        if parsed is not None and (not parsed.is_finite() or parsed <= 0 or parsed.as_tuple().exponent < -3):
            raise ValueError("gross_weight_kg must be positive with at most 3 decimals")
        return parsed


class RFQDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20_000)

    @field_validator("subject")
    @classmethod
    def single_line_subject(cls, value):
        if any(ch in value for ch in "\r\n") or not value.strip():
            raise ValueError("Subject must be a single nonblank line")
        return value.strip()

    @field_validator("body")
    @classmethod
    def nonblank_body(cls, value):
        if not value.strip():
            raise ValueError("Body must not be blank")
        return value.replace("\r\n", "\n")


class MarkSent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sent_at: datetime | None = None

    @field_validator("sent_at")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("sent_at must include a timezone")
        return value
