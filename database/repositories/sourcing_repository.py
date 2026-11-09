"""Tenant-scoped access to sourcing quote requests and carrier RFQ drafts."""
from sqlalchemy import func, select

from database.models import CarrierRFQ, QuoteRequest
from database.repositories._scoped import create_owned, require_tenant, scoped_statement

OPEN_SOURCING_STATUSES = ("NO_CARRIER_AVAILABLE", "RFQ_DRAFTED", "AWAITING_REPLIES")


def _page(limit, offset):
    if not 1 <= limit <= 1000 or offset < 0:
        raise ValueError("limit must be 1..1000 and offset nonnegative")


def create_quote_request(session, tenant_id, **values):
    return create_owned(session, QuoteRequest, tenant_id, values)


def get_quote_request(session, tenant_id, quote_request_id, *, for_update=False):
    query = scoped_statement(QuoteRequest, tenant_id).where(QuoteRequest.id == quote_request_id)
    return session.scalar(query.with_for_update() if for_update else query)


def find_open_quote_request(session, tenant_id, fingerprint):
    """Oldest open sourcing request with the same shipment fingerprint, locked for update."""
    return session.scalar(scoped_statement(QuoteRequest, tenant_id).where(
        QuoteRequest.request_fingerprint == fingerprint,
        QuoteRequest.sourcing_status.in_(OPEN_SOURCING_STATUSES),
    ).order_by(QuoteRequest.created_at, QuoteRequest.id).limit(1).with_for_update())


def list_sourcing_requests(session, tenant_id, *, status=None, limit=50, offset=0):
    _page(limit, offset)
    query = scoped_statement(QuoteRequest, tenant_id).where(QuoteRequest.sourcing_status != "NONE")
    if status is not None:
        query = query.where(QuoteRequest.sourcing_status == status)
    return list(session.scalars(query.order_by(QuoteRequest.created_at.desc(), QuoteRequest.id).limit(limit).offset(offset)))


def create_carrier_rfq(session, tenant_id, **values):
    return create_owned(session, CarrierRFQ, tenant_id, values)


def get_carrier_rfq(session, tenant_id, rfq_id, *, for_update=False):
    query = scoped_statement(CarrierRFQ, tenant_id).where(CarrierRFQ.id == rfq_id)
    return session.scalar(query.with_for_update() if for_update else query)


def get_rfq_by_reference_code(session, tenant_id, reference_code):
    return session.scalar(scoped_statement(CarrierRFQ, tenant_id).where(CarrierRFQ.reference_code == reference_code))


def get_rfq_by_outbound_message_id(session, tenant_id, message_id):
    return session.scalar(scoped_statement(CarrierRFQ, tenant_id).where(CarrierRFQ.outbound_message_id == message_id))


def reference_code_exists(session, tenant_id, reference_code):
    return get_rfq_by_reference_code(session, tenant_id, reference_code) is not None


def list_carrier_rfqs(session, tenant_id, *, quote_request_id=None, status=None):
    query = scoped_statement(CarrierRFQ, tenant_id)
    if quote_request_id is not None:
        query = query.where(CarrierRFQ.quote_request_id == quote_request_id)
    if status is not None:
        query = query.where(CarrierRFQ.status == status)
    return list(session.scalars(query.order_by(CarrierRFQ.created_at, CarrierRFQ.reference_code)))


def rfq_status_counts(session, tenant_id, quote_request_id):
    require_tenant(tenant_id)
    rows = session.execute(select(CarrierRFQ.status, func.count()).where(
        CarrierRFQ.tenant_id == tenant_id, CarrierRFQ.quote_request_id == quote_request_id
    ).group_by(CarrierRFQ.status))
    return {status: count for status, count in rows}


def drafted_supplier_ids(session, tenant_id, quote_request_id):
    require_tenant(tenant_id)
    return set(session.scalars(select(CarrierRFQ.supplier_id).where(
        CarrierRFQ.tenant_id == tenant_id, CarrierRFQ.quote_request_id == quote_request_id)))
