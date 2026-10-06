from uuid import UUID
from sqlalchemy import JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from database.base import Base, UUIDPrimaryKey, TenantOwned, CreatedAt, owned, tenant_fk


class RateEvent(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    """Append-only management audit and precise old/new rate version links."""
    __tablename__ = "rate_events"
    __table_args__ = (*owned(), tenant_fk("old_rate_id", "rates"), tenant_fk("new_rate_id", "rates"))
    old_rate_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    new_rate_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    action: Mapped[str] = mapped_column(String(40))
    changes: Mapped[list] = mapped_column(JSON)
