from sqlalchemy import or_, select

from database.models import LocationAlias, EquipmentAlias
from database.repositories._scoped import require_tenant


def resolve_location_aliases(session, tenant_id, alias):
    # Return matches rather than guessing if a mapping is ambiguous.
    require_tenant(tenant_id)
    rows = list(session.scalars(select(LocationAlias).where(
        LocationAlias.alias == alias,
        or_(LocationAlias.tenant_id == tenant_id, LocationAlias.tenant_id.is_(None)))))
    private = [row for row in rows if row.tenant_id == tenant_id]
    return private if private else rows


def resolve_equipment_aliases(session, tenant_id, alias):
    require_tenant(tenant_id)
    rows = list(session.scalars(select(EquipmentAlias).where(
        EquipmentAlias.alias == alias,
        or_(EquipmentAlias.tenant_id == tenant_id, EquipmentAlias.tenant_id.is_(None)))))
    private = [row for row in rows if row.tenant_id == tenant_id]
    return private if private else rows
