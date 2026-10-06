from sqlalchemy import Boolean, String, true
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, UUIDPrimaryKey, TenantOwned, Timestamps, owned
from database.models.enums import SUPPLIER_TYPE


class Supplier(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "suppliers"
    __table_args__ = owned()
    name: Mapped[str] = mapped_column(String(255))
    supplier_type: Mapped[str] = mapped_column(SUPPLIER_TYPE)
    external_reference: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
