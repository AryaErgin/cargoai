import os

from fastapi import FastAPI, HTTPException
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


MAX_INPUT_LENGTH = 20_000

app = FastAPI(title="CargoAI Parser API")
app.include_router(rates_router)
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
def quote_spot(request: SpotQuoteRequest):
    try:
        with session_scope(get_engine()) as session:
            result = price_quote(session, request.to_pricing_request(session), persist=request.persist)
            if result.status != "PRICED":
                status = 409 if result.status in {"AMBIGUOUS_RATE", "AMBIGUOUS_PRICING_RULE"} else 422
                raise HTTPException(status_code=status, detail=result.model_dump(mode="json"))
            return result.model_dump(mode="json")
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
        raise HTTPException(status_code=502, detail="RFQ parsing service failed") from None
    return {"type": "spot_rfq", "result": result}


@app.post("/parse/tender")
def parse_tender(request: ParseRequest):
    text = validate_text(request.text)
    try:
        result = parse_freight_tender(text)
    except Exception:
        raise HTTPException(status_code=502, detail="Tender parsing service failed") from None
    return {"type": "freight_tender", "result": result}
