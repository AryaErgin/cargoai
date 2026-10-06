from uuid import UUID
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from api.access import local_demo_tenant
from database.models import Location, EquipmentType, Customer, Tenant
from database.session import get_engine, session_scope
from pricing.resolvers import resolve_location, resolve_equipment
from pricing.exceptions import PricingError

router = APIRouter(prefix="/quote/lookups")


@contextmanager
def lookup_session(tenant_id):
    try:
        with session_scope(get_engine()) as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None or not tenant.is_active or tenant.slug != "demo-forwarder":
                raise HTTPException(403, "Configured tenant must be the active synthetic demo-forwarder")
            yield session
    except HTTPException:
        raise
    except PricingError as error:
        raise HTTPException(error.http_status, {"status": error.code, "error": str(error),
                                               "metadata": error.metadata}) from None
    except Exception:
        raise HTTPException(503, "Pricing lookup database/service unavailable") from None


@router.get("")
def lookups(tenant_id: UUID = Depends(local_demo_tenant)):
    with lookup_session(tenant_id) as session:
        return {
            "locations": [{"id": str(row.id), "label": f"{row.name} ({row.un_locode or row.code or row.country_code or row.id})"}
                          for row in session.scalars(select(Location).order_by(Location.name))],
            "equipment": [{"id": str(row.id), "label": row.canonical_code}
                          for row in session.scalars(select(EquipmentType).where(
                              EquipmentType.supported.is_(True), EquipmentType.transport_mode == "OCEAN",
                              EquipmentType.canonical_code.in_(["20GP", "40GP", "40HC"])))],
            "customers": [{"id": str(row.id), "label": row.name}
                          for row in session.scalars(select(Customer).where(
                              Customer.tenant_id == tenant_id, Customer.is_active.is_(True)).order_by(Customer.name))],
            "demo_data": True,
        }


@router.get("/resolve")
def resolve(kind: str, value: str = Query(min_length=1, max_length=255),
            tenant_id: UUID = Depends(local_demo_tenant)):
    resolver = {"location": resolve_location, "equipment": resolve_equipment}.get(kind)
    if resolver is None:
        raise HTTPException(422, "Reference kind must be location or equipment")
    with lookup_session(tenant_id) as session:
        row = resolver(session, tenant_id, value)
        return {"id": str(row.id)}
