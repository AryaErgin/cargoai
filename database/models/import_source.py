from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, Integer, JSON, String, Text, Uuid, CheckConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, UUIDPrimaryKey, TenantOwned, Timestamps, CreatedAt, UTCDateTime, utcnow, owned, tenant_fk
from database.models.enums import SOURCE_TYPE, IMPORT_STATUS


class SourceDocument(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "source_documents"
    __table_args__ = (*owned(), tenant_fk("supplier_id", "suppliers"))
    supplier_id: Mapped[UUID | None] = mapped_column(Uuid)
    source_type: Mapped[str] = mapped_column(SOURCE_TYPE)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    checksum: Mapped[str | None] = mapped_column(String(128))
    storage_reference: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ImportProfile(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "import_profiles"
    __table_args__ = (*owned(), tenant_fk("supplier_id", "suppliers"))
    supplier_id: Mapped[UUID | None] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(SOURCE_TYPE)
    configuration_json: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class ImportJob(UUIDPrimaryKey, TenantOwned, CreatedAt, Base):
    __tablename__ = "import_jobs"
    __table_args__ = (*owned(), tenant_fk("source_document_id", "source_documents"),
                      tenant_fk("import_profile_id", "import_profiles"),
                      CheckConstraint("rows_received >= 0 AND rows_imported >= 0 AND rows_rejected >= 0", name="nonnegative_rows"))
    source_document_id: Mapped[UUID | None] = mapped_column(Uuid)
    import_profile_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(IMPORT_STATUS, default="PENDING", server_default="PENDING")
    rows_received: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rows_imported: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
