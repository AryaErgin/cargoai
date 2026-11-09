from datetime import date, timedelta
from decimal import Decimal
import re
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from conftest import FIXED_NOW
from database.models import CarrierRFQ, QuoteRequest, Tenant
from sourcing import service
from sourcing.exceptions import (AmbiguousRate, InvalidSourcingRequest, InvalidTransition, RateAvailable,
                                 ReferenceCodeRequired, SendingDisabled, SourcingNotFound)
from sourcing.outbound import DraftOnlySender

pytestmark = pytest.mark.usefixtures("no_network")


def counts(session):
    return (session.scalar(select(func.count()).select_from(QuoteRequest)),
            session.scalar(select(func.count()).select_from(CarrierRFQ)))


def start(world, now=FIXED_NOW, **changes):
    return service.start_sourcing(world.session, world.tenant_id, world.request(**changes), now=now)


def rfqs_of(world, result):
    return list(world.session.scalars(select(CarrierRFQ).where(
        CarrierRFQ.quote_request_id == UUID(result["quote_request_id"])).order_by(CarrierRFQ.reference_code)))


# --- B6: start_sourcing ----------------------------------------------------------------------------

@pytest.mark.parametrize("changes,status", [
    ({}, "PRICED"), ({"requested_currency": "GBP"}, "MISSING_FX")])
def test_lane_with_rate_is_not_sourced(sourcing_world, changes, status):
    world = sourcing_world
    with pytest.raises(RateAvailable) as raised:
        start(world, origin="CNSHA", destination="TRAMR", effective_date=date(2026, 10, 15), **changes)
    assert raised.value.http_status == 409 and raised.value.metadata["pricing_status"] == status
    assert counts(world.session) == (0, 0)


def test_ambiguous_rate_is_not_sourced(sourcing_world):
    world = sourcing_world
    supplier = world.suppliers["Example Blue Line"]
    for _ in range(2):
        world.rate(world.tenant_id, supplier, "TRMER", "CNSHA", valid_from=date(2026, 11, 1),
                   valid_to=date(2026, 11, 30), created_at=FIXED_NOW)
    with pytest.raises(AmbiguousRate) as raised:
        start(world)
    assert raised.value.code == "AMBIGUOUS_RATE" and raised.value.http_status == 409
    assert counts(world.session) == (0, 0)


def test_reverse_lane_creates_request_and_drafts(sourcing_world):
    world = sourcing_world
    result = start(world, customer_id=world.customer_id, incoterm=" fob ", commodity="Machine  parts",
                   gross_weight_kg="18000.250")
    assert result["sourcing_status"] == "RFQ_DRAFTED" and result["rfq_drafts_created"] == 2
    assert result["already_existed"] is False and result["nothing_sent"] is True
    request = world.session.get(QuoteRequest, UUID(result["quote_request_id"]))
    assert request.tenant_id == world.tenant_id and request.customer_id == world.customer_id
    assert (request.origin_location_id, request.destination_location_id) == (world.locations["TRMER"], world.locations["CNSHA"])
    assert request.container_count == 2 and request.effective_date == date(2026, 11, 20)
    assert request.dangerous_goods is False and request.incoterm == "FOB" and request.commodity == "Machine parts"
    assert request.gross_weight_kg == Decimal("18000.250") and request.requested_currency == "USD"
    assert re.fullmatch(r"[0-9a-f]{64}", request.request_fingerprint)
    rfqs = rfqs_of(world, result)
    assert {rfq.status for rfq in rfqs} == {"DRAFT"}
    assert sorted(rfq.selection_metadata["rank"] for rfq in rfqs) == [1, 2]
    assert all(rfq.response_due_at == FIXED_NOW + timedelta(hours=48) for rfq in rfqs)
    assert all(rfq.template_version == "rfq_ocean_fcl_en_v2" and rfq.sent_at is None for rfq in rfqs)
    assert {rfq.recipient_email for rfq in rfqs} == {"quotes.anatolia@example.com", "rfq.blueline@example.com"}
    assert len({rfq.outbound_message_id for rfq in rfqs}) == 2


def test_start_is_idempotent(sourcing_world):
    world = sourcing_world
    first = start(world, gross_weight_kg="18000.5")
    second = start(world, gross_weight_kg="18000.500", now=FIXED_NOW + timedelta(hours=1))
    assert second["quote_request_id"] == first["quote_request_id"]
    assert second["already_existed"] is True and second["rfq_drafts_created"] == 0
    assert counts(world.session) == (1, 2)
    third = start(world, container_count=3)
    assert third["quote_request_id"] != first["quote_request_id"] and counts(world.session) == (2, 4)


def test_response_hours_configurable(sourcing_world, monkeypatch):
    monkeypatch.setenv("CARGOAI_RFQ_RESPONSE_HOURS", "72")
    rfqs = rfqs_of(sourcing_world, start(sourcing_world))
    assert all(rfq.response_due_at == FIXED_NOW + timedelta(hours=72) for rfq in rfqs)


def test_no_carrier_available_then_recovers(sourcing_world):
    world = sourcing_world
    result = start(world, origin="TRAMR", destination="TRMER")
    assert result["sourcing_status"] == "NO_CARRIER_AVAILABLE" and result["rfq_drafts_created"] == 0
    assert counts(world.session) == (1, 0)
    world.carrier(world.tenant_id, "Coastal Feeder", emails=("feeder@example.com",),
                  capabilities=[{"origin_country_code": "TR", "destination_country_code": "TR"}])
    again = start(world, origin="TRAMR", destination="TRMER")
    assert again["quote_request_id"] == result["quote_request_id"] and again["already_existed"] is True
    assert again["sourcing_status"] == "RFQ_DRAFTED" and again["rfq_drafts_created"] == 1
    assert counts(world.session) == (1, 1)


def test_cancelled_request_does_not_block_a_new_one(sourcing_world):
    world = sourcing_world
    first = start(world)
    for rfq in rfqs_of(world, first):
        service.cancel_rfq(world.session, world.tenant_id, rfq.id)
    assert world.session.get(QuoteRequest, UUID(first["quote_request_id"])).sourcing_status == "CANCELLED"
    second = start(world)
    assert second["quote_request_id"] != first["quote_request_id"] and second["already_existed"] is False


@pytest.mark.parametrize("changes", [
    {"dangerous_goods": True}, {"dangerous_goods": None}, {"dangerous_goods": "false"},
    {"container_count": 0}, {"container_count": 1.5}, {"container_count": True},
    {"gross_weight_kg": 18000.5}, {"gross_weight_kg": "12.3456"}, {"gross_weight_kg": "0"}, {"gross_weight_kg": "-1"},
    {"gross_weight_kg": "1e5"}, {"requested_currency": "US"}, {"tenant_id": "x"}, {"sell_price": "100"},
    {"commodity": "x" * 300},
])
def test_invalid_input_rejected_without_writes(sourcing_world, changes):
    world = sourcing_world
    with pytest.raises(InvalidSourcingRequest) as raised:
        start(world, **changes)
    assert raised.value.http_status == 422
    assert counts(world.session) == (0, 0)


def test_customer_of_other_tenant_rejected(sourcing_world):
    world = sourcing_world
    other = world.new_tenant("other")
    from database.repositories.customer_repository import create_customer
    foreign = create_customer(world.session, other, name="Foreign customer")
    with pytest.raises(InvalidSourcingRequest) as raised:
        start(world, customer_id=foreign.id)
    assert raised.value.code == "INVALID_REQUEST" and raised.value.http_status == 422
    assert counts(world.session) == (0, 0)


def test_unsupported_equipment_and_unknown_location_rejected(sourcing_world):
    world = sourcing_world
    with pytest.raises(InvalidSourcingRequest):
        start(world, equipment="40OT")
    with pytest.raises(InvalidSourcingRequest):
        service.start_sourcing(world.session, world.tenant_id, {**world.request(), "origin_location_id": uuid4()})
    assert counts(world.session) == (0, 0)


def test_tenant_required_and_active(sourcing_world):
    world = sourcing_world
    with pytest.raises(InvalidSourcingRequest):
        service.start_sourcing(world.session, str(world.tenant_id), world.request())
    with pytest.raises(SourcingNotFound):
        service.start_sourcing(world.session, uuid4(), world.request())
    world.session.get(Tenant, world.tenant_id).is_active = False
    world.session.flush()
    with pytest.raises(SourcingNotFound):
        start(world)


def test_other_tenant_cannot_see_or_reuse_requests(sourcing_world):
    world = sourcing_world
    result = start(world)
    other = world.new_tenant("other")
    world.carrier(other, "Other Tenant Carrier", capabilities=[{"origin_country_code": "TR", "destination_country_code": "CN"}])
    other_result = service.start_sourcing(world.session, other, world.request(), now=FIXED_NOW)
    assert other_result["quote_request_id"] != result["quote_request_id"] and other_result["already_existed"] is False
    assert {rfq.recipient_email for rfq in rfqs_of(world, other_result)} == {"rates@example.com"}
    with pytest.raises(SourcingNotFound):
        service.get_sourcing_status(world.session, other, UUID(result["quote_request_id"]))
    with pytest.raises(SourcingNotFound):
        service.get_request_detail(world.session, other, UUID(result["quote_request_id"]))
    rfq = rfqs_of(world, result)[0]
    for call in (service.approve_rfq, service.cancel_rfq, service.mark_rfq_sent, service.get_rfq):
        with pytest.raises(SourcingNotFound):
            call(world.session, other, rfq.id)
    assert rfq.status == "DRAFT"


# --- B7: draft lifecycle ---------------------------------------------------------------------------

@pytest.fixture
def drafted(sourcing_world):
    result = start(sourcing_world)
    return sourcing_world, result, rfqs_of(sourcing_world, result)


def request_status(world, result):
    world.session.expire_all()
    return world.session.get(QuoteRequest, UUID(result["quote_request_id"])).sourcing_status


def test_update_draft_keeps_reference(drafted):
    world, _, (rfq, _) = drafted
    detail = service.update_rfq_draft(world.session, world.tenant_id, rfq.id, {
        "subject": f"Rate request {rfq.reference_code}", "body": f"Hello\r\nPlease quote.\n{rfq.reference_code}\n"})
    assert detail["subject"] == f"Rate request {rfq.reference_code}" and "\r" not in rfq.body
    for payload in ({"subject": "No reference", "body": rfq.body}, {"subject": rfq.subject, "body": "No reference"}):
        with pytest.raises(ReferenceCodeRequired) as raised:
            service.update_rfq_draft(world.session, world.tenant_id, rfq.id, payload)
        assert raised.value.http_status == 422
    for payload in ({"subject": f"{rfq.reference_code}\nBcc: x@example.com", "body": rfq.body},
                    {"subject": rfq.subject, "body": "   "}, {"subject": rfq.subject, "body": rfq.body, "to": "x"}):
        with pytest.raises(InvalidSourcingRequest):
            service.update_rfq_draft(world.session, world.tenant_id, rfq.id, payload)
    assert rfq.subject == f"Rate request {rfq.reference_code}"


def test_approve_then_edit_is_invalid(drafted):
    world, result, (rfq, _) = drafted
    detail = service.approve_rfq(world.session, world.tenant_id, rfq.id, now=FIXED_NOW)
    assert detail["status"] == "APPROVED" and rfq.approved_at == FIXED_NOW
    assert request_status(world, result) == "AWAITING_REPLIES"
    with pytest.raises(InvalidTransition) as raised:
        service.update_rfq_draft(world.session, world.tenant_id, rfq.id, {"subject": rfq.subject, "body": rfq.body})
    assert raised.value.http_status == 409
    with pytest.raises(InvalidTransition):
        service.approve_rfq(world.session, world.tenant_id, rfq.id)


def test_mark_sent_requires_approval(drafted):
    world, result, (rfq, _) = drafted
    with pytest.raises(InvalidTransition):
        service.mark_rfq_sent(world.session, world.tenant_id, rfq.id)
    assert request_status(world, result) == "RFQ_DRAFTED"
    service.approve_rfq(world.session, world.tenant_id, rfq.id, now=FIXED_NOW)
    for sent_at in (FIXED_NOW + timedelta(hours=2), FIXED_NOW - timedelta(minutes=1)):
        with pytest.raises(InvalidSourcingRequest):
            service.mark_rfq_sent(world.session, world.tenant_id, rfq.id, {"sent_at": sent_at},
                                  now=FIXED_NOW + timedelta(hours=1))
    with pytest.raises(InvalidSourcingRequest):
        service.mark_rfq_sent(world.session, world.tenant_id, rfq.id, {"sent_at": FIXED_NOW.replace(tzinfo=None)})
    detail = service.mark_rfq_sent(world.session, world.tenant_id, rfq.id, {"sent_at": FIXED_NOW + timedelta(minutes=30)},
                                   now=FIXED_NOW + timedelta(hours=1))
    assert detail["status"] == "SENT" and detail["send_channel"] == "MANUAL"
    assert rfq.sent_at == FIXED_NOW + timedelta(minutes=30)
    with pytest.raises(InvalidTransition):
        service.mark_rfq_sent(world.session, world.tenant_id, rfq.id)


def test_send_rfq_with_default_sender_changes_nothing(drafted):
    world, result, (rfq, _) = drafted
    with pytest.raises(InvalidTransition):
        service.send_rfq(world.session, world.tenant_id, rfq.id, DraftOnlySender(), from_address="ops@example.com")
    service.approve_rfq(world.session, world.tenant_id, rfq.id, now=FIXED_NOW)
    with pytest.raises(SendingDisabled):
        service.send_rfq(world.session, world.tenant_id, rfq.id, DraftOnlySender(), from_address="ops@example.com")
    world.session.expire_all()
    stored = world.session.get(CarrierRFQ, rfq.id)
    assert stored.status == "APPROVED" and stored.sent_at is None and stored.send_channel is None


def test_cancel_transitions(drafted):
    world, result, (first, second) = drafted
    service.approve_rfq(world.session, world.tenant_id, first.id, now=FIXED_NOW)
    service.cancel_rfq(world.session, world.tenant_id, first.id, now=FIXED_NOW)
    assert first.status == "CANCELLED" and first.cancelled_at == FIXED_NOW
    assert request_status(world, result) == "AWAITING_REPLIES"
    with pytest.raises(InvalidTransition):
        service.cancel_rfq(world.session, world.tenant_id, first.id)
    with pytest.raises(InvalidTransition):
        service.approve_rfq(world.session, world.tenant_id, first.id)
    service.cancel_rfq(world.session, world.tenant_id, second.id)
    assert request_status(world, result) == "CANCELLED"


def test_replied_rfq_cannot_be_cancelled(drafted):
    world, _, (rfq, _) = drafted
    rfq.status = "REPLIED"
    world.session.flush()
    with pytest.raises(InvalidTransition):
        service.cancel_rfq(world.session, world.tenant_id, rfq.id)


def test_export_eml_requires_approval(drafted):
    world, _, (rfq, _) = drafted
    with pytest.raises(InvalidTransition):
        service.export_rfq_eml(world.session, world.tenant_id, rfq.id, from_address="ops@example.com")
    service.approve_rfq(world.session, world.tenant_id, rfq.id, now=FIXED_NOW)
    raw = service.export_rfq_eml(world.session, world.tenant_id, rfq.id, from_address="ops@example.com")
    assert rfq.outbound_message_id.encode() in raw and rfq.status == "APPROVED"


def test_status_counts_overdue_and_rate_available(drafted):
    world, result, (first, second) = drafted
    request_id = UUID(result["quote_request_id"])
    status = service.get_sourcing_status(world.session, world.tenant_id, request_id, now=FIXED_NOW)
    assert status == {"quote_request_id": str(request_id), "sourcing_status": "RFQ_DRAFTED", "rfq_drafts": 2,
                      "rfqs_sent": 0, "replies_received": 0, "rate_available": False, "rfqs_overdue": 0}
    service.approve_rfq(world.session, world.tenant_id, first.id, now=FIXED_NOW)
    service.mark_rfq_sent(world.session, world.tenant_id, first.id, now=FIXED_NOW + timedelta(minutes=5))
    later = FIXED_NOW + timedelta(hours=49)
    status = service.get_sourcing_status(world.session, world.tenant_id, request_id, now=later)
    assert status["rfqs_sent"] == 1 and status["rfqs_overdue"] == 1 and status["sourcing_status"] == "AWAITING_REPLIES"
    assert service.get_sourcing_status(world.session, world.tenant_id, request_id, now=FIXED_NOW)["rfqs_overdue"] == 0
    world.rate(world.tenant_id, world.suppliers["Example Blue Line"], "TRMER", "CNSHA",
               valid_from=date(2026, 11, 1), valid_to=date(2026, 11, 30))
    assert service.get_sourcing_status(world.session, world.tenant_id, request_id, now=later)["rate_available"] is True


def test_internal_views_include_review_data(drafted):
    world, result, rfqs = drafted
    detail = service.get_request_detail(world.session, world.tenant_id, UUID(result["quote_request_id"]), now=FIXED_NOW)
    assert {rfq["carrier"] for rfq in detail["rfqs"]} == {"Example Anatolia NVOCC", "Example Blue Line"}
    assert all(rfq["overdue"] is False and rfq["selection_metadata"]["selector_version"] for rfq in detail["rfqs"])
    listing = service.list_requests(world.session, world.tenant_id, now=FIXED_NOW)
    assert [row["quote_request_id"] for row in listing] == [result["quote_request_id"]]
    assert listing[0]["rfq_counts"] == {"DRAFT": 2}
    assert service.list_requests(world.session, world.tenant_id, status="CANCELLED") == []
    with pytest.raises(InvalidSourcingRequest):
        service.list_requests(world.session, world.tenant_id, limit=5000)
    with pytest.raises(SourcingNotFound):
        service.get_rfq(world.session, world.tenant_id, uuid4())


# --- Optional commodity / gross weight and the idempotency key -------------------------------------

@pytest.mark.parametrize("first,second", [
    ({}, {"commodity": "   ", "gross_weight_kg": None}),
    ({"commodity": "Machine parts"}, {"commodity": "  machine   PARTS "}),
    ({"gross_weight_kg": "18500"}, {"gross_weight_kg": "18500.000"}),
])
def test_equivalent_cargo_facts_reuse_open_request(sourcing_world, first, second):
    world = sourcing_world
    created = start(world, **first)
    again = start(world, **second)
    assert again["quote_request_id"] == created["quote_request_id"] and again["already_existed"] is True
    assert counts(world.session) == (1, 2)


@pytest.mark.parametrize("first,second", [
    ({}, {"commodity": "Machine parts"}),
    ({}, {"gross_weight_kg": "18500"}),
    ({"gross_weight_kg": "18500"}, {"gross_weight_kg": "18500.5"}),
    ({"commodity": "Machine parts"}, {"commodity": "Textiles"}),
])
def test_different_cargo_facts_create_a_new_request(sourcing_world, first, second):
    """Drafts already state the old facts; reusing them would send carriers a wrong weight/commodity."""
    world = sourcing_world
    created = start(world, **first)
    again = start(world, **second)
    assert again["quote_request_id"] != created["quote_request_id"] and again["already_existed"] is False


def test_blank_commodity_stored_as_absent(sourcing_world):
    world = sourcing_world
    result = start(world, commodity=" \t ")
    request = world.session.get(QuoteRequest, UUID(result["quote_request_id"]))
    assert request.commodity is None and request.gross_weight_kg is None
    assert result["rfq_drafts_created"] == 2
