from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, UUIDPrimaryKey, TenantOwned, CreatedAt, owned


class ExchangeRate(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (*owned(),
        UniqueConstraint("tenant_id", "base_currency", "quote_currency", "effective_from", name="uq_fx_pair_start"),
        CheckConstraint("rate > 0", name="positive_fx_rate"),
        CheckConstraint("effective_to IS NULL OR effective_from <= effective_to", name="fx_validity_order"),
        Index("ix_fx_lookup", "tenant_id", "base_currency", "quote_currency", "effective_from", "effective_to"))
    base_currency: Mapped[str] = mapped_column(String(3))
    quote_currency: Mapped[str] = mapped_column(String(3))
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str | None] = mapped_column(String(255))
