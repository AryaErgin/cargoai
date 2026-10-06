"""Manual rate lifecycle and append-only audit links.

Revision ID: 0004_management
Revises: 0003_commercial
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_management"
down_revision = "0003_commercial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("rates", sa.Column("status", sa.String(8),
        sa.CheckConstraint("status IN ('DRAFT','ACTIVE','EXPIRED','ARCHIVED')", name="ck_rates_sheet_status"),
        nullable=False, server_default="ACTIVE"))
    op.execute(sa.text("UPDATE rates SET status = 'ARCHIVED' WHERE is_active = false"))
    op.add_column("rate_sheets", sa.Column("commercial_type", sa.String(8),
        sa.CheckConstraint("commercial_type IN ('SPOT','CONTRACT')", name="ck_rate_sheets_supplier_commercial_type"),
        nullable=False, server_default="SPOT"))
    # Mixed legacy sheets default to SPOT; individual rate types remain untouched.
    op.add_column("rate_sheets", sa.Column("notes", sa.Text(), nullable=True))
    op.create_table("rate_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("old_rate_id", sa.Uuid(), nullable=True),
        sa.Column("new_rate_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id", "old_rate_id"], ["rates.tenant_id", "rates.id"], name="fk_old_rate_id_rates_tenant"),
        sa.ForeignKeyConstraint(["tenant_id", "new_rate_id"], ["rates.tenant_id", "rates.id"], name="fk_new_rate_id_rates_tenant"))
    for column in ("tenant_id", "old_rate_id", "new_rate_id"):
        op.create_index(f"ix_rate_events_{column}", "rate_events", [column])


def downgrade():
    if not op.get_context().as_sql and op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM rate_events")):
        raise RuntimeError("Cannot discard rate management audit history; export it explicitly before downgrade")
    op.drop_table("rate_events")
    op.drop_column("rate_sheets", "notes")
    op.drop_column("rate_sheets", "commercial_type")
    op.drop_column("rates", "status")
