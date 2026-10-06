"""Internal/dev manual-rate routes. Explicit tenant IDs are not authentication."""
from datetime import date
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from database.session import get_engine, session_scope
from rate_management import service
from rate_management.models import SheetCreate, RateCreate, ChargeRequest, ChargeCreate, RateVersion, RatePatch, DeactivateRequest, Status, CommercialType
from rate_management.exceptions import RateManagementError

router = APIRouter(prefix="/admin/rates", tags=["Internal development: rate management"])


def execute(function, tenant_id, *args, **kwargs):
    try:
        with session_scope(get_engine()) as session:
            return function(session, tenant_id, *args, **kwargs)
    except RateManagementError as error:
        raise HTTPException(status_code=error.http_status,
            detail={"status": error.code, "error": str(error), "metadata": error.metadata}) from None
    except Exception:
        raise HTTPException(status_code=503, detail="Rate management database/service unavailable") from None


@router.post("/sheets")
def create_sheet(request: SheetCreate):
    return execute(service.create_rate_sheet, request.tenant_id, request)


@router.post("")
def create_rate(request: RateCreate):
    return execute(service.create_rate, request.tenant_id, request)


@router.get("")
def list_rates(tenant_id: UUID, supplier_id: UUID | None = None, origin: UUID | None = None,
               destination: UUID | None = None, equipment: UUID | None = None,
               mode: Literal["OCEAN_FCL"] | None = None, status: Status | None = None,
               valid_on: date | None = None, commercial_type: CommercialType | None = None,
               limit: int = Query(default=50, ge=1, le=1000), offset: int = Query(default=0, ge=0)):
    return execute(service.list_rates, tenant_id, supplier_id=supplier_id, origin=origin,
        destination=destination, equipment=equipment, mode=mode, status=status,
        valid_on=valid_on, commercial_type=commercial_type, limit=limit, offset=offset)


@router.get("/{rate_id}")
def get_rate(rate_id: UUID, tenant_id: UUID):
    return execute(service.get_rate_details, tenant_id, rate_id)


@router.post("/{rate_id}/charges")
def add_charge(rate_id: UUID, request: ChargeRequest):
    charge = ChargeCreate.model_validate(request.model_dump(exclude={"tenant_id"}))
    return execute(service.add_rate_charge, request.tenant_id, rate_id, charge)


@router.post("/{rate_id}/update")
def update_rate(rate_id: UUID, request: RatePatch):
    return execute(service.update_rate, request.tenant_id, rate_id, request)


@router.post("/{rate_id}/version")
def version_rate(rate_id: UUID, request: RateVersion):
    return execute(service.create_rate_version, request.tenant_id, rate_id, request)


@router.post("/{rate_id}/deactivate")
def deactivate_rate(rate_id: UUID, request: DeactivateRequest):
    return execute(service.deactivate_rate, request.tenant_id, rate_id, status=request.status)
