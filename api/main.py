import os
import logging

from fastapi import FastAPI, HTTPException, Depends
from uuid import UUID
from api.access import local_demo_tenant
from api.quote_view import customer_quote
from api.lookups import router as lookups_router
from database.models import Tenant
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text as sql_text

from database.session import get_engine, session_scope
from pricing.api_models import SpotQuoteRequest
from pricing.exceptions import PricingError
from pricing.pricing_engine import price_quote
from pydantic import ValidationError

from app.spot_parser import parse_spot_rfq
from app.tender_parser import parse_freight_tender
from api.rates import router as rates_router
from api.emails import router as emails_router


MAX_INPUT_LENGTH = 20_000
logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="CargoAI Parser API")
app.include_router(rates_router)
app.include_router(lookups_router)
app.include_router(emails_router)
frontend_origin = os.environ.get(
    "CARGOAI_FRONTEND_ORIGIN", "http://localhost:3000"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    allow_credentials=False,
)


class ParseRequest(BaseModel):
    text: str


def validate_text(text: str) -> str:
    if not text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")
    if len(text) > MAX_INPUT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"text must be at most {MAX_INPUT_LENGTH} characters",
        )
    return text


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def database_health():
    try:
        with get_engine().connect() as connection:
            connection.execute(sql_text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return {"status": "ok", "database": "connected"}


@app.post("/quote/spot", tags=["Internal development"])
def quote_spot(request: SpotQuoteRequest, tenant_id: UUID = Depends(local_demo_tenant)):
    if request.tenant_id is not None and request.tenant_id != tenant_id:
        raise HTTPException(403, "Company access does not match configured demo tenant")
    try:
        with session_scope(get_engine()) as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None or not tenant.is_active or tenant.slug != "demo-forwarder":
                raise HTTPException(403, "Configured tenant must be the active synthetic demo-forwarder")
            result = price_quote(session, request.to_pricing_request(session, tenant_id), persist=request.persist)
            if result.status != "PRICED":
                status = 409 if result.status in {"AMBIGUOUS_RATE", "AMBIGUOUS_PRICING_RULE"} else 422
                raise HTTPException(status_code=status, detail={"status": result.status, "error": result.error})
            return customer_quote(session, result)
    except HTTPException:
        raise
    except PricingError as error:
        raise HTTPException(status_code=error.http_status, detail={"status": error.code, "error": str(error),
                                                                 "metadata": error.metadata}) from None
    except ValidationError:
        raise HTTPException(status_code=422, detail="Invalid structured pricing request") from None
    except Exception:
        raise HTTPException(status_code=503, detail="Pricing database/service unavailable") from None


@app.post("/parse/spot")
def parse_spot(request: ParseRequest):
    text = validate_text(request.text)
    try:
        result = parse_spot_rfq(text)
    except Exception:
        logger.exception("RFQ parsing failed")
        raise HTTPException(status_code=502, detail="RFQ parsing service failed") from None
    return {"type": "spot_rfq", "result": result}


@app.post("/parse/tender")
def parse_tender(request: ParseRequest):
    text = validate_text(request.text)
    try:
        result = parse_freight_tender(text)
    except Exception:
        logger.exception("Tender parsing failed")
        raise HTTPException(status_code=502, detail="Tender parsing service failed") from None
    return {"type": "freight_tender", "result": result}
