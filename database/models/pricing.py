from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Uuid, true
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, UUIDPrimaryKey, TenantOwned, Timestamps, owned, tenant_fk
from database.models.enums import RATE_MODE, RULE_TYPE
from database.models.rate import targeting_checks, validity_check


class PricingRule(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "pricing_rules"
    __table_args__ = (*owned(), tenant_fk("customer_id", "customers"),
                      tenant_fk("origin_group_id", "location_groups"), tenant_fk("destination_group_id", "location_groups"),
                      *targeting_checks(), validity_check())
    customer_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(255))
    mode: Mapped[str | None] = mapped_column(RATE_MODE)
    rule_type: Mapped[str] = mapped_column(RULE_TYPE)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    currency: Mapped[str | None] = mapped_column(String(3))
    origin_location_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("locations.id"))
    origin_group_id: Mapped[UUID | None] = mapped_column(Uuid)
    destination_location_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("locations.id"))
    destination_group_id: Mapped[UUID | None] = mapped_column(Uuid)
    equipment_type_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("equipment_types.id"))
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
