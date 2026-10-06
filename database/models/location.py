from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, Numeric, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, UUIDPrimaryKey, Timestamps, CreatedAt, TenantOwned, owned, tenant_fk
from database.models.enums import LOCATION_TYPE


class Location(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "locations"
    code: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(255))
    country_code: Mapped[str | None] = mapped_column(String(2))
    location_type: Mapped[str] = mapped_column(LOCATION_TYPE)
    un_locode: Mapped[str | None] = mapped_column(String(5), index=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7))


class LocationAlias(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "location_aliases"
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    alias: Mapped[str] = mapped_column(String(255), index=True)
    source: Mapped[str | None] = mapped_column(String(255))


class LocationGroup(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "location_groups"
    __table_args__ = (*owned(), UniqueConstraint("tenant_id", "name"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)


class LocationGroupMember(TenantOwned, Base):
    __tablename__ = "location_group_members"
    __table_args__ = (tenant_fk("location_group_id", "location_groups"),)
    location_group_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), primary_key=True)
