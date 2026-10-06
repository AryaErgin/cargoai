from sqlalchemy import func, select

from database.models import Location, LocationAlias, EquipmentType, EquipmentAlias
from database.repositories._scoped import require_tenant
from pricing.exceptions import AmbiguousReference, InvalidPricingRequest


def _resolve(session, tenant_id, text, model, alias_model, alias_target, canonical_columns):
    require_tenant(tenant_id)
    normalized = text.strip().upper()
    if not normalized:
        raise InvalidPricingRequest("Location/equipment reference must not be empty")
    for private in (True, False):
        owner = alias_model.tenant_id == tenant_id if private else alias_model.tenant_id.is_(None)
        ids = set(session.scalars(select(alias_target).where(owner, func.upper(alias_model.alias) == normalized)))
        if ids:
            return _one(session, model, ids, text)
    from sqlalchemy import or_
    ids = set(session.scalars(select(model.id).where(or_(*(func.upper(column) == normalized for column in canonical_columns)))))
    return _one(session, model, ids, text)


def _one(session, model, ids, text):
    if not ids:
        raise InvalidPricingRequest(f"Unknown {model.__tablename__} reference: {text}")
    if len(ids) != 1:
        raise AmbiguousReference(f"Ambiguous {model.__tablename__} reference: {text}",
                                 metadata={"matched_ids": sorted(str(value) for value in ids)})
    return session.get(model, next(iter(ids)))


def resolve_location(session, tenant_id, text):
    return _resolve(session, tenant_id, text, Location, LocationAlias, LocationAlias.location_id,
                    (Location.name, Location.code, Location.un_locode))


def resolve_equipment(session, tenant_id, text):
    return _resolve(session, tenant_id, text, EquipmentType, EquipmentAlias, EquipmentAlias.equipment_type_id,
                    (EquipmentType.canonical_code, EquipmentType.display_name))
