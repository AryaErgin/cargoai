from sqlalchemy import Boolean, String, true
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, UUIDPrimaryKey, TenantOwned, Timestamps, owned


class Customer(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "customers"
    __table_args__ = owned()
    name: Mapped[str] = mapped_column(String(255))
    external_reference: Mapped[str | None] = mapped_column(String(255))
    default_currency: Mapped[str | None] = mapped_column(String(3))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
