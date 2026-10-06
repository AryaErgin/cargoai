from sqlalchemy import select

from database.models import Tenant
from database.repositories._scoped import require_tenant


def create_tenant(session, *, name, slug, default_currency="EUR", timezone=None):
    if not name.strip() or not slug.strip():
        raise ValueError("Tenant name and slug must not be empty")
    row = Tenant(name=name, slug=slug, default_currency=default_currency, timezone=timezone)
    session.add(row)
    session.flush()
    return row


def get_tenant(session, tenant_id):
    return session.scalar(select(Tenant).where(Tenant.id == require_tenant(tenant_id)))
