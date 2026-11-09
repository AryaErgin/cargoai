"""Customer-safe carrier sourcing routes: identifiers, status and counts only.

Never returns carrier names, contact emails, reference codes, RFQ bodies or prices. Internal review
(drafts, recipients, selection metadata) is available only through `sourcing.cli` in phase 1.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from api.access import local_demo_tenant
from database.models import Tenant
from database.session import get_engine, session_scope
from sourcing import service
from sourcing.exceptions import SourcingError
from sourcing.models import StartSourcing

router = APIRouter(prefix="/sourcing", tags=["Carrier sourcing (drafts only)"])


def execute(function, tenant_id, *args, **kwargs):
    try:
        with session_scope(get_engine()) as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None or not tenant.is_active or tenant.slug != "demo-forwarder":
                raise HTTPException(403, "Configured tenant must be the active synthetic demo-forwarder")
            return function(session, tenant_id, *args, **kwargs)
    except HTTPException:
        raise
    except SourcingError as error:
        # Metadata is internal (selection/pricing detail); customers get the code and message only.
        raise HTTPException(status_code=error.http_status, detail={"status": error.code, "error": str(error)}) from None
    except Exception:
        raise HTTPException(status_code=503, detail="Sourcing database/service unavailable") from None


@router.post("/requests")
def start_sourcing(request: StartSourcing, tenant_id: UUID = Depends(local_demo_tenant)):
    result = execute(service.start_sourcing, tenant_id, request)
    return {key: result[key] for key in ("quote_request_id", "sourcing_status", "rfq_drafts_created",
                                         "already_existed", "nothing_sent")}


@router.get("/requests/{quote_request_id}")
def sourcing_status(quote_request_id: UUID, tenant_id: UUID = Depends(local_demo_tenant)):
    result = execute(service.get_sourcing_status, tenant_id, quote_request_id)
    return {key: result[key] for key in ("quote_request_id", "sourcing_status", "rfq_drafts", "rfqs_sent",
                                         "replies_received", "rate_available", "rfqs_overdue")}
