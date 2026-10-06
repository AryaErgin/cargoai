"""Separate supplier commercial terms from customer commitments.

Revision ID: 0003_commercial
Revises: 0002_pricing
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_commercial"
down_revision = "0002_pricing"
branch_labels = None
depends_on = None


def upgrade():
    # Existing rows remain supplier SPOT rates; no dates or amounts are inferred.
    op.add_column("rates", sa.Column("commercial_type", sa.String(8),
        sa.CheckConstraint("commercial_type IN ('SPOT', 'CONTRACT')", name="ck_rates_supplier_commercial_type"),
        nullable=False, server_default="SPOT"))
    for name in ("market_notes", "capacity_notes", "service_frequency_notes", "disruption_notes"):
        op.add_column("rates", sa.Column(name, sa.Text(), nullable=True))
    # Rename rather than copy/drop so every existing customer expiry is retained.
    op.alter_column("quotes", "valid_until", new_column_name="quote_valid_until", existing_type=sa.Date())
    op.add_column("quotes", sa.Column("quote_valid_from", sa.Date(),
        sa.CheckConstraint("quote_valid_from IS NULL OR quote_valid_until IS NULL OR quote_valid_from <= quote_valid_until",
                           name="ck_quotes_quote_validity_order"), nullable=True))
    op.add_column("quotes", sa.Column("commercial_type", sa.String(14),
        sa.CheckConstraint("commercial_type IN ('SPOT', 'CONTRACT', 'CUSTOMER_FIXED')", name="ck_quotes_commercial_type"),
        sa.CheckConstraint("commercial_type <> 'CUSTOMER_FIXED' OR customer_id IS NOT NULL", name="ck_quotes_customer_fixed_requires_customer"),
        nullable=False, server_default="SPOT"))


def downgrade():
    # Do not silently erase customer commitments while reverting to an older schema.
    if not op.get_context().as_sql:
        count = op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM quotes WHERE commercial_type = 'CUSTOMER_FIXED'"))
        if count:
            raise RuntimeError("Cannot downgrade while CUSTOMER_FIXED commitments exist; archive/export them explicitly first")
    op.drop_column("quotes", "commercial_type")
    op.drop_column("quotes", "quote_valid_from")
    op.alter_column("quotes", "quote_valid_until", new_column_name="valid_until", existing_type=sa.Date())
    for name in ("disruption_notes", "service_frequency_notes", "capacity_notes", "market_notes", "commercial_type"):
        op.drop_column("rates", name)
