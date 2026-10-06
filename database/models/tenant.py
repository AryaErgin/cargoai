from sqlalchemy import Boolean, String, true
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, UUIDPrimaryKey, Timestamps


class Tenant(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "tenants"
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    default_currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    timezone: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
