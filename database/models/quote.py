from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKeyConstraint, JSON, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, synonym

from database.base import Base, UUIDPrimaryKey, TenantOwned, Timestamps, CreatedAt, owned, tenant_fk
from database.models.enums import RATE_MODE, QUOTE_STATUS, COMMERCIAL_TYPE


class QuoteRequest(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "quote_requests"
    __table_args__ = (*owned(), tenant_fk("customer_id", "customers"))
    customer_id: Mapped[UUID | None] = mapped_column(Uuid)
    source_text: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(RATE_MODE)


class Quote(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "quotes"
    __table_args__ = (*owned(), tenant_fk("quote_request_id", "quote_requests"), tenant_fk("customer_id", "customers"),
        CheckConstraint("quote_valid_from IS NULL OR quote_valid_until IS NULL OR quote_valid_from <= quote_valid_until", name="quote_validity_order"),
        CheckConstraint("commercial_type <> 'CUSTOMER_FIXED' OR customer_id IS NOT NULL", name="customer_fixed_requires_customer"))
    quote_request_id: Mapped[UUID | None] = mapped_column(Uuid)
    customer_id: Mapped[UUID | None] = mapped_column(Uuid)
    currency: Mapped[str] = mapped_column(String(3))
    commercial_type: Mapped[str] = mapped_column(COMMERCIAL_TYPE, default="SPOT", server_default="SPOT")
    buy_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    sell_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    margin_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    margin_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    status: Mapped[str] = mapped_column(QUOTE_STATUS, default="DRAFT", server_default="DRAFT")
    quote_valid_from: Mapped[date | None] = mapped_column(Date)
    quote_valid_until: Mapped[date | None] = mapped_column(Date)
    # Preserve old ORM callers without maintaining two competing date columns.
    valid_until = synonym("quote_valid_until")
    calculation_json: Mapped[dict | None] = mapped_column(JSON)


class QuoteLine(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "quote_lines"
    __table_args__ = (*owned(), tenant_fk("quote_id", "quotes"), tenant_fk("rate_id", "rates"),
                      tenant_fk("rate_charge_id", "rate_charges"),
                      CheckConstraint("rate_charge_id IS NULL OR rate_id IS NOT NULL", name="charge_requires_rate"),
                      ForeignKeyConstraint(["tenant_id", "rate_id", "rate_charge_id"],
                                           ["rate_charges.tenant_id", "rate_charges.rate_id", "rate_charges.id"],
                                           name="fk_quote_line_rate_charge_provenance"))
    quote_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    rate_id: Mapped[UUID | None] = mapped_column(Uuid)
    rate_charge_id: Mapped[UUID | None] = mapped_column(Uuid)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    unit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    currency: Mapped[str] = mapped_column(String(3))
    basis: Mapped[str] = mapped_column(String(100))
    calculation_json: Mapped[dict | None] = mapped_column(JSON)
