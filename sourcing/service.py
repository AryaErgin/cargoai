"""Transactional, tenant-scoped sourcing commands. No LLM, no network; nothing is sent from here
unless an explicit `RFQSender` is passed to `send_rfq` (V1 only has the draft-only sender)."""
from datetime import timezone
from functools import wraps
from hashlib import sha256
import json
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.base import utcnow
from database.models import EquipmentType, Location, Supplier, Tenant
from database.repositories.sourcing_repository import (create_carrier_rfq, create_quote_request, drafted_supplier_ids,
    find_open_quote_request, get_carrier_rfq, get_quote_request, list_carrier_rfqs, list_sourcing_requests)
from pricing.exceptions import InvalidPricingRequest, PricingError
from pricing.models import PricingRequest
from pricing.pricing_engine import price_quote
from sourcing.carrier_selector import select_carriers
from sourcing.deadlines import count_overdue, is_overdue, response_due_at
from sourcing.exceptions import (AmbiguousRate, InvalidSourcingRequest, InvalidTransition, RateAvailable,
                                 ReferenceCodeRequired, SourcingConflict, SourcingError, SourcingNotFound)
from sourcing.models import MarkSent, RFQDraftUpdate, StartSourcing
from sourcing.outbound import SendResult, build_outbound, render_eml
from sourcing.reference import new_outbound_message_id, new_reference_code
from sourcing.rfq_template import TEMPLATE_VERSION, RFQContext, render_rfq

MODE = "OCEAN_FCL"
SENT_STATUSES = frozenset({"SENT", "REPLIED", "CLOSED"})


def command(function):
    @wraps(function)
    def run(session, tenant_id, *args, **kwargs):
        if not isinstance(tenant_id, UUID):
            raise InvalidSourcingRequest("An explicit tenant UUID is required")
        try:
            # Same SQLite savepoint guard as rate_management: never let the savepoint commit early.
            connection = session.connection()
            if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql("BEGIN")
            with session.begin_nested():
                tenant = session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
                if tenant is None or not tenant.is_active:
                    raise SourcingNotFound("Tenant is unknown or inactive")
                return function(session, tenant_id, *args, **kwargs)
        except ValidationError as error:
            raise InvalidSourcingRequest("Invalid sourcing input", metadata={
                "errors": error.errors(include_context=False, include_input=False, include_url=False)}) from None
        except IntegrityError:
            raise SourcingConflict("Concurrent/conflicting sourcing write; reload and retry") from None
    return run


def _now(now):
    now = now or utcnow()
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(timezone.utc)


def _input(model, value):
    return model.model_validate(value.model_dump() if isinstance(value, BaseModel) else value)


def request_fingerprint(request: StartSourcing) -> str:
    """sha256 of the normalized shipment facts; same facts (and customer) => same open request."""
    payload = {"mode": MODE, "customer_id": str(request.customer_id) if request.customer_id else None,
               "origin_location_id": str(request.origin_location_id),
               "destination_location_id": str(request.destination_location_id),
               "equipment_type_id": str(request.equipment_type_id), "container_count": request.container_count,
               "effective_date": request.effective_date.isoformat(), "requested_currency": request.requested_currency,
               "dangerous_goods": request.dangerous_goods, "incoterm": request.incoterm,
               "commodity": request.commodity.casefold() if request.commodity else None,
               "gross_weight_kg": format(request.gross_weight_kg.normalize(), "f") if request.gross_weight_kg else None}
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _pricing_request(tenant_id, row):
    return PricingRequest(tenant_id=tenant_id, customer_id=row.customer_id, mode=MODE,
        origin_location_id=row.origin_location_id, destination_location_id=row.destination_location_id,
        equipment_type_id=row.equipment_type_id, container_count=row.container_count,
        effective_date=row.effective_date, requested_currency=row.requested_currency,
        dangerous_goods=row.dangerous_goods, incoterm=row.incoterm)


def _require_sourcing_gap(session, tenant_id, request):
    """Re-price server-side; only NO_RATE_FOUND may proceed. Never trusts the client's claim."""
    try:
        result = price_quote(session, _pricing_request(tenant_id, request), persist=False)
    except InvalidPricingRequest as error:
        raise InvalidSourcingRequest(str(error)) from None
    except PricingError:
        # A rate was selected but its configuration cannot be priced; sourcing is not the remedy.
        raise RateAvailable("A rate exists for this shipment but cannot be priced; review the rate configuration") from None
    if result.status == "AMBIGUOUS_RATE":
        raise AmbiguousRate("Multiple rates match this shipment; resolve the rate ambiguity instead of sourcing")
    if result.status != "NO_RATE_FOUND":
        raise RateAvailable("A rate is available for this shipment; recalculate the quote instead",
                            metadata={"pricing_status": result.status})


def _draft_rfqs(session, tenant_id, quote_request, now):
    candidates = select_carriers(session, tenant_id, mode=MODE, origin_location_id=quote_request.origin_location_id,
        destination_location_id=quote_request.destination_location_id,
        equipment_type_id=quote_request.equipment_type_id,
        exclude_supplier_ids=drafted_supplier_ids(session, tenant_id, quote_request.id))
    if not candidates:
        return 0
    tenant = session.get(Tenant, tenant_id)
    origin = session.get(Location, quote_request.origin_location_id)
    destination = session.get(Location, quote_request.destination_location_id)
    equipment = session.get(EquipmentType, quote_request.equipment_type_id)
    due = response_due_at(now)
    taken = set()
    for candidate in candidates:
        code = new_reference_code(session, tenant_id, taken=taken)
        taken.add(code)
        subject, body = render_rfq(RFQContext(reference_code=code, origin_name=origin.name,
            origin_locode=origin.un_locode, destination_name=destination.name,
            destination_locode=destination.un_locode, equipment_code=equipment.canonical_code,
            container_count=quote_request.container_count, cargo_ready_date=quote_request.effective_date,
            dangerous_goods=quote_request.dangerous_goods, response_due_at=due, forwarder_name=tenant.name,
            incoterm=quote_request.incoterm, commodity=quote_request.commodity,
            gross_weight_kg=quote_request.gross_weight_kg))
        create_carrier_rfq(session, tenant_id, quote_request_id=quote_request.id, supplier_id=candidate.supplier.id,
            supplier_contact_id=candidate.contact.id, recipient_email=candidate.contact.email, reference_code=code,
            outbound_message_id=new_outbound_message_id(), subject=subject, body=body,
            template_version=TEMPLATE_VERSION, status="DRAFT", response_due_at=due,
            selection_metadata=candidate.metadata)
    return len(candidates)


def _start_response(quote_request, created, already_existed):
    return {"quote_request_id": str(quote_request.id), "sourcing_status": quote_request.sourcing_status,
            "rfq_drafts_created": created, "already_existed": already_existed, "nothing_sent": True}


@command
def start_sourcing(session, tenant_id, request, *, now=None):
    request = _input(StartSourcing, request)
    if request.dangerous_goods:
        raise InvalidSourcingRequest("Dangerous-goods shipments cannot be sourced in V1")
    now = _now(now)
    _require_sourcing_gap(session, tenant_id, request)
    fingerprint = request_fingerprint(request)
    existing = find_open_quote_request(session, tenant_id, fingerprint)
    if existing is not None:
        created = 0
        if existing.sourcing_status == "NO_CARRIER_AVAILABLE":
            # Carriers may have been configured since; drafting stays idempotent per supplier.
            created = _draft_rfqs(session, tenant_id, existing, now)
            if created:
                existing.sourcing_status = "RFQ_DRAFTED"
                session.flush()
        return _start_response(existing, created, True)
    quote_request = create_quote_request(session, tenant_id, customer_id=request.customer_id, mode=MODE,
        origin_location_id=request.origin_location_id, destination_location_id=request.destination_location_id,
        equipment_type_id=request.equipment_type_id, container_count=request.container_count,
        effective_date=request.effective_date, requested_currency=request.requested_currency,
        dangerous_goods=False, incoterm=request.incoterm, commodity=request.commodity,
        gross_weight_kg=request.gross_weight_kg, sourcing_status="NO_CARRIER_AVAILABLE",
        request_fingerprint=fingerprint)
    created = _draft_rfqs(session, tenant_id, quote_request, now)
    quote_request.sourcing_status = "RFQ_DRAFTED" if created else "NO_CARRIER_AVAILABLE"
    session.flush()
    return _start_response(quote_request, created, False)


# --- Draft lifecycle -------------------------------------------------------------------------

def _locked_rfq(session, tenant_id, rfq_id):
    rfq = get_carrier_rfq(session, tenant_id, rfq_id, for_update=True) if isinstance(rfq_id, UUID) else None
    if rfq is None:
        raise SourcingNotFound()
    return rfq


def _require_status(rfq, statuses, action):
    if rfq.status not in statuses:
        raise InvalidTransition(f"Cannot {action} an RFQ in status {rfq.status}",
                                metadata={"status": rfq.status, "allowed": sorted(statuses)})


def _mark_awaiting(session, tenant_id, quote_request_id):
    request = get_quote_request(session, tenant_id, quote_request_id, for_update=True)
    if request.sourcing_status == "RFQ_DRAFTED":
        request.sourcing_status = "AWAITING_REPLIES"


def _refresh_after_cancel(session, tenant_id, quote_request_id):
    request = get_quote_request(session, tenant_id, quote_request_id, for_update=True)
    rfqs = list_carrier_rfqs(session, tenant_id, quote_request_id=quote_request_id)
    if rfqs and all(rfq.status == "CANCELLED" for rfq in rfqs) and request.sourcing_status in {"RFQ_DRAFTED", "AWAITING_REPLIES"}:
        request.sourcing_status = "CANCELLED"


@command
def update_rfq_draft(session, tenant_id, rfq_id, request):
    request = _input(RFQDraftUpdate, request)
    rfq = _locked_rfq(session, tenant_id, rfq_id)
    _require_status(rfq, {"DRAFT"}, "edit")
    if rfq.reference_code not in request.subject or rfq.reference_code not in request.body:
        raise ReferenceCodeRequired(f"Subject and body must both keep the reference code {rfq.reference_code}")
    rfq.subject, rfq.body = request.subject, request.body
    session.flush()
    return rfq_detail(session, tenant_id, rfq)


@command
def approve_rfq(session, tenant_id, rfq_id, *, now=None):
    rfq = _locked_rfq(session, tenant_id, rfq_id)
    _require_status(rfq, {"DRAFT"}, "approve")
    rfq.status, rfq.approved_at = "APPROVED", _now(now)
    _mark_awaiting(session, tenant_id, rfq.quote_request_id)
    session.flush()
    return rfq_detail(session, tenant_id, rfq)


@command
def cancel_rfq(session, tenant_id, rfq_id, *, now=None):
    rfq = _locked_rfq(session, tenant_id, rfq_id)
    _require_status(rfq, {"DRAFT", "APPROVED", "SENT"}, "cancel")
    rfq.status, rfq.cancelled_at = "CANCELLED", _now(now)
    session.flush()
    _refresh_after_cancel(session, tenant_id, rfq.quote_request_id)
    session.flush()
    return rfq_detail(session, tenant_id, rfq)


@command
def mark_rfq_sent(session, tenant_id, rfq_id, request=None, *, now=None):
    """Record that an operator sent the approved .eml manually (no network)."""
    request = _input(MarkSent, request or {})
    now = _now(now)
    rfq = _locked_rfq(session, tenant_id, rfq_id)
    _require_status(rfq, {"APPROVED"}, "mark as sent")
    sent_at = (request.sent_at or now).astimezone(timezone.utc)
    if sent_at > now or (rfq.approved_at is not None and sent_at < rfq.approved_at):
        raise InvalidSourcingRequest("sent_at must be between approval and now")
    rfq.status, rfq.sent_at, rfq.send_channel = "SENT", sent_at, "MANUAL"
    _mark_awaiting(session, tenant_id, rfq.quote_request_id)
    session.flush()
    return rfq_detail(session, tenant_id, rfq)


@command
def send_rfq(session, tenant_id, rfq_id, sender, *, from_address, now=None):
    """Hand an APPROVED RFQ snapshot to `sender`. DraftOnlySender raises and nothing changes."""
    rfq = _locked_rfq(session, tenant_id, rfq_id)
    _require_status(rfq, {"APPROVED"}, "send")
    result = sender.send(build_outbound(rfq, from_address))
    if not isinstance(result, SendResult) or result.sent_at.tzinfo is None:
        raise SourcingError("Sender returned an invalid result")
    rfq.status, rfq.sent_at, rfq.send_channel = "SENT", result.sent_at.astimezone(timezone.utc), sender.name
    _mark_awaiting(session, tenant_id, rfq.quote_request_id)
    session.flush()
    return rfq_detail(session, tenant_id, rfq)


@command
def export_rfq_eml(session, tenant_id, rfq_id, *, from_address):
    rfq = _locked_rfq(session, tenant_id, rfq_id)
    _require_status(rfq, {"APPROVED", "SENT"}, "export")
    return render_eml(rfq, from_address)


# --- Read models -----------------------------------------------------------------------------

def _sourcing_request(session, tenant_id, quote_request_id):
    row = get_quote_request(session, tenant_id, quote_request_id) if isinstance(quote_request_id, UUID) else None
    if row is None or row.request_fingerprint is None:
        raise SourcingNotFound()
    return row


def _rate_available(session, tenant_id, row):
    try:
        return price_quote(session, _pricing_request(tenant_id, row), persist=False).status != "NO_RATE_FOUND"
    except PricingError:
        return False


@command
def get_sourcing_status(session, tenant_id, quote_request_id, *, now=None):
    """Customer-safe status: identifiers, status and counts only - never carriers, emails or prices."""
    row = _sourcing_request(session, tenant_id, quote_request_id)
    rfqs = list_carrier_rfqs(session, tenant_id, quote_request_id=row.id)
    return {"quote_request_id": str(row.id), "sourcing_status": row.sourcing_status,
            "rfq_drafts": sum(1 for rfq in rfqs if rfq.status != "CANCELLED"),
            "rfqs_sent": sum(1 for rfq in rfqs if rfq.sent_at is not None),
            "replies_received": sum(1 for rfq in rfqs if rfq.status == "REPLIED"),
            "rate_available": _rate_available(session, tenant_id, row),
            "rfqs_overdue": count_overdue(rfqs, _now(now))}


def _iso(value):
    return value.isoformat() if value is not None else None


def rfq_detail(session, tenant_id, rfq, *, now=None):
    """INTERNAL view (carrier, recipient, body). Backend/CLI only - never a customer route."""
    supplier = session.get(Supplier, rfq.supplier_id)
    return {"rfq_id": str(rfq.id), "quote_request_id": str(rfq.quote_request_id), "status": rfq.status,
            "reference_code": rfq.reference_code, "carrier": supplier.name, "supplier_id": str(rfq.supplier_id),
            "recipient_email": rfq.recipient_email, "subject": rfq.subject, "body": rfq.body,
            "template_version": rfq.template_version, "outbound_message_id": rfq.outbound_message_id,
            "send_channel": rfq.send_channel, "response_due_at": _iso(rfq.response_due_at),
            "overdue": is_overdue(rfq, _now(now)), "approved_at": _iso(rfq.approved_at),
            "sent_at": _iso(rfq.sent_at), "cancelled_at": _iso(rfq.cancelled_at),
            "selection_metadata": rfq.selection_metadata}


def _request_summary(session, tenant_id, row, now):
    origin = session.get(Location, row.origin_location_id)
    destination = session.get(Location, row.destination_location_id)
    equipment = session.get(EquipmentType, row.equipment_type_id)
    rfqs = list_carrier_rfqs(session, tenant_id, quote_request_id=row.id)
    counts = {}
    for rfq in rfqs:
        counts[rfq.status] = counts.get(rfq.status, 0) + 1
    return {"quote_request_id": str(row.id), "sourcing_status": row.sourcing_status,
            "created_at": _iso(row.created_at), "origin": origin.name if origin else None,
            "destination": destination.name if destination else None,
            "equipment": equipment.canonical_code if equipment else None, "container_count": row.container_count,
            "effective_date": _iso(row.effective_date), "rfq_counts": counts,
            "rfqs_overdue": count_overdue(rfqs, now)}


@command
def list_requests(session, tenant_id, *, status=None, limit=50, offset=0, now=None):
    now = _now(now)
    try:
        rows = list_sourcing_requests(session, tenant_id, status=status, limit=limit, offset=offset)
    except ValueError as error:
        raise InvalidSourcingRequest(str(error)) from None
    return [_request_summary(session, tenant_id, row, now) for row in rows]


@command
def get_request_detail(session, tenant_id, quote_request_id, *, now=None):
    now = _now(now)
    row = _sourcing_request(session, tenant_id, quote_request_id)
    return {**_request_summary(session, tenant_id, row, now), "customer_id": str(row.customer_id) if row.customer_id else None,
            "requested_currency": row.requested_currency, "incoterm": row.incoterm, "commodity": row.commodity,
            "gross_weight_kg": format(row.gross_weight_kg, "f") if row.gross_weight_kg is not None else None,
            "rfqs": [rfq_detail(session, tenant_id, rfq, now=now)
                     for rfq in list_carrier_rfqs(session, tenant_id, quote_request_id=row.id)]}


@command
def get_rfq(session, tenant_id, rfq_id, *, now=None):
    rfq = get_carrier_rfq(session, tenant_id, rfq_id) if isinstance(rfq_id, UUID) else None
    if rfq is None:
        raise SourcingNotFound()
    return rfq_detail(session, tenant_id, rfq, now=now)
