from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, Uuid, true
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, UUIDPrimaryKey
from database.models.enums import TRANSPORT_MODE


class EquipmentType(UUIDPrimaryKey, Base):
    __tablename__ = "equipment_types"
    canonical_code: Mapped[str] = mapped_column(String(50), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    transport_mode: Mapped[str] = mapped_column(TRANSPORT_MODE)
    supported: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class EquipmentAlias(UUIDPrimaryKey, Base):
    __tablename__ = "equipment_aliases"
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    equipment_type_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("equipment_types.id"), index=True)
    alias: Mapped[str] = mapped_column(String(255), index=True)
