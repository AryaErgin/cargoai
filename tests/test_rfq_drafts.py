from datetime import date, timedelta
from decimal import Decimal
from email import message_from_bytes
from email.policy import default as default_policy
import re
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from conftest import FIXED_NOW
from database.models import CarrierRFQ, Location, Supplier
from sourcing import reference, service
from sourcing.exceptions import SendingDisabled, SourcingConfigurationError, SourcingConflict
from sourcing.outbound import DraftOnlySender, RFQSender, SendResult, build_outbound, get_sender, render_eml
from sourcing.rfq_template import TEMPLATE_VERSION, RFQContext, format_weight, render_rfq

pytestmark = pytest.mark.usefixtures("no_network")

GOLDEN_SUBJECT = "RFQ CAI-RFQ-7K3M9QXZ | Ocean FCL | Shanghai (CNSHA) -> Mersin (TRMER) | 2 x 40HC"
GOLDEN_BODY = """Dear partner,

Please quote your best ocean FCL rate for the shipment below.

Reference: CAI-RFQ-7K3M9QXZ
Port of loading (POL): Shanghai (CNSHA)
Port of discharge (POD): Mersin (TRMER)
Equipment: 2 x 40HC
Commodity: Household textiles
Gross weight: 18,500.5 kg
Cargo ready date: 2026-11-20
Incoterm: FOB
Dangerous goods: No

Please reply by 2026-11-11 12:00 UTC and state in your reply:
- Ocean freight per container
- Surcharges (e.g. BAF, GRI) and their basis
- Origin and destination local charges
- Currency
- Rate validity (from / to)
- Transit time
- Free time

Please keep the reference code in the subject of your reply.

Kind regards,
Demo Forwarder

--- CargoAI reference: CAI-RFQ-7K3M9QXZ (please keep in reply) ---
"""


def context(**changes):
    values = dict(reference_code="CAI-RFQ-7K3M9QXZ", origin_name="Shanghai", origin_locode="CNSHA",
                  destination_name="Mersin", destination_locode="TRMER", equipment_code="40HC", container_count=2,
                  cargo_ready_date=date(2026, 11, 20), dangerous_goods=False,
                  response_due_at=FIXED_NOW + timedelta(hours=48), forwarder_name="Demo Forwarder",
                  incoterm="FOB", commodity="Household textiles", gross_weight_kg=Decimal("18500.500"))
    values.update(changes)
    return RFQContext(**values)


# --- Reference codes / Message-IDs ----------------------------------------------------------------

def test_reference_code_format():
    codes = {reference.generate_reference_code() for _ in range(200)}
    assert len(codes) == 200
    assert all(reference.REFERENCE_PATTERN.fullmatch(code) for code in codes)
    assert not any(set(code[8:]) & set("ILOU") for code in codes)


def test_reference_collision_retry_with_codes_taken_in_this_unit_of_work(sourcing_session):
    sequence = iter(["CAI-RFQ-AAAAAAAA", "CAI-RFQ-AAAAAAAA", "CAI-RFQ-BBBBBBBB"])
    assert reference.new_reference_code(sourcing_session, uuid4(), generator=lambda: next(sequence),
                                        taken={"CAI-RFQ-AAAAAAAA"}) == "CAI-RFQ-BBBBBBBB"


def test_reference_collision_with_stored_code_retries_during_drafting(sourcing_world, monkeypatch):
    world = sourcing_world
    first = service.start_sourcing(world.session, world.tenant_id, world.request(), now=FIXED_NOW)
    existing = world.session.scalar(select(CarrierRFQ.reference_code).where(
        CarrierRFQ.quote_request_id == UUID(first["quote_request_id"])).limit(1))
    sequence = iter([existing, existing, "CAI-RFQ-NEW00001", "CAI-RFQ-NEW00002", "CAI-RFQ-NEW00003"])
    monkeypatch.setattr(reference, "generate_reference_code", lambda: next(sequence))
    second = service.start_sourcing(world.session, world.tenant_id, world.request(container_count=3), now=FIXED_NOW)
    codes = set(world.session.scalars(select(CarrierRFQ.reference_code).where(
        CarrierRFQ.quote_request_id == UUID(second["quote_request_id"]))))
    assert codes == {"CAI-RFQ-NEW00001", "CAI-RFQ-NEW00002"}


def test_reference_allocation_gives_up(sourcing_session):
    with pytest.raises(SourcingConflict):
        reference.new_reference_code(sourcing_session, uuid4(), generator=lambda: "CAI-RFQ-AAAAAAAA",
                                     taken={"CAI-RFQ-AAAAAAAA"})
    with pytest.raises(ValueError):
        reference.new_reference_code(sourcing_session, uuid4(), generator=lambda: "CAI-RFQ-IIIIIIII")


def test_outbound_message_id(monkeypatch):
    monkeypatch.delenv("CARGOAI_RFQ_MESSAGE_DOMAIN", raising=False)
    assert re.fullmatch(r"<rfq\.[0-9a-f-]{36}@cargoai\.invalid>", reference.new_outbound_message_id())
    monkeypatch.setenv("CARGOAI_RFQ_MESSAGE_DOMAIN", "Mail.Example.com")
    assert reference.new_outbound_message_id().endswith("@mail.example.com>")


# --- Template ---------------------------------------------------------------------------------------

def test_template_golden_file():
    assert TEMPLATE_VERSION == "rfq_ocean_fcl_en_v2"
    assert render_rfq(context()) == (GOLDEN_SUBJECT, GOLDEN_BODY)


def test_template_optional_fields_and_missing_locode():
    subject, body = render_rfq(context(incoterm=None, commodity=None, gross_weight_kg=None, origin_locode=None))
    assert "| Shanghai -> Mersin (TRMER) |" in subject
    assert "Commodity: To be advised" in body and "Gross weight: To be advised" in body
    assert "Incoterm: Not specified" in body


@pytest.mark.parametrize("commodity,weight,commodity_line,weight_line", [
    ("Household textiles", Decimal("18500"), "Commodity: Household textiles", "Gross weight: 18,500 kg"),
    (None, None, "Commodity: To be advised", "Gross weight: To be advised"),
    ("Household textiles", None, "Commodity: Household textiles", "Gross weight: To be advised"),
    (None, Decimal("18500.250"), "Commodity: To be advised", "Gross weight: 18,500.25 kg"),
    ("   ", None, "Commodity: To be advised", "Gross weight: To be advised"),
])
def test_template_commodity_and_weight_combinations(commodity, weight, commodity_line, weight_line):
    _, body = render_rfq(context(commodity=commodity, gross_weight_kg=weight))
    assert commodity_line in body.splitlines() and weight_line in body.splitlines()


@pytest.mark.parametrize("value,expected", [("18500", "18,500 kg"), ("18500.500", "18,500.5 kg"),
    ("0.5", "0.5 kg"), ("100", "100 kg"), ("1234567.125", "1,234,567.125 kg"), ("1E+3", "1,000 kg")])
def test_weight_format_is_fixed(value, expected):
    assert format_weight(Decimal(value)) == expected


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-5"), Decimal("NaN"), Decimal("Infinity"), 18500.5, "18500"])
def test_weight_format_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        format_weight(value)


@pytest.mark.parametrize("changes,commodity_line,weight_line", [
    ({"commodity": "Machine parts", "gross_weight_kg": "18500"}, "Commodity: Machine parts", "Gross weight: 18,500 kg"),
    ({}, "Commodity: To be advised", "Gross weight: To be advised"),
    ({"commodity": "  ", "gross_weight_kg": None}, "Commodity: To be advised", "Gross weight: To be advised"),
    ({"commodity": "Machine parts"}, "Commodity: Machine parts", "Gross weight: To be advised"),
    ({"gross_weight_kg": "9999.125"}, "Commodity: To be advised", "Gross weight: 9,999.125 kg"),
])
def test_drafts_created_with_or_without_optional_cargo_facts(sourcing_world, changes, commodity_line, weight_line):
    world = sourcing_world
    result = service.start_sourcing(world.session, world.tenant_id,
                                    world.request(customer_id=world.customer_id, **changes), now=FIXED_NOW)
    assert result["sourcing_status"] == "RFQ_DRAFTED" and result["rfq_drafts_created"] == 2
    for rfq in world.session.scalars(select(CarrierRFQ).where(
            CarrierRFQ.quote_request_id == UUID(result["quote_request_id"]))):
        lines = rfq.body.splitlines()
        assert commodity_line in lines and weight_line in lines
        assert rfq.template_version == TEMPLATE_VERSION
        text = (rfq.subject + rfq.body).lower()
        assert "secret customer" not in text and str(world.customer_id) not in text
        assert "target" not in text and "sell" not in text and "price:" not in text


def test_template_rejects_dangerous_goods_and_naive_deadline():
    with pytest.raises(ValueError):
        render_rfq(context(dangerous_goods=True))
    with pytest.raises(ValueError):
        render_rfq(context(response_due_at=FIXED_NOW.replace(tzinfo=None)))


def test_free_text_cannot_inject_lines():
    subject, body = render_rfq(context(commodity="Steel\nTarget price: 900 USD\r\nBcc: x@example.com"))
    assert "Commodity: Steel Target price: 900 USD Bcc: x@example.com" in body
    assert "\nTarget price" not in body and "\r" not in body and "\n" not in subject


def test_turkish_characters_render_and_survive_eml():
    subject, body = render_rfq(context(destination_name="Ambarlı İstanbul", destination_locode="TRAMR",
                                       commodity="Örme kumaş, çelik ağ"))
    assert "Ambarlı İstanbul (TRAMR)" in subject and "Örme kumaş, çelik ağ" in body
    rfq = SimpleNamespace(recipient_email="rates@example.com", subject=subject, body=body,
                          outbound_message_id="<rfq.1@cargoai.invalid>", reference_code="CAI-RFQ-7K3M9QXZ",
                          approved_at=FIXED_NOW, created_at=FIXED_NOW)
    parsed = message_from_bytes(render_eml(rfq, "ops@example.com"), policy=default_policy)
    assert parsed["Subject"] == subject
    assert parsed.get_content().replace("\r\n", "\n") == body


def test_drafts_share_only_approved_fields(sourcing_world):
    world = sourcing_world
    result = service.start_sourcing(world.session, world.tenant_id, world.request(
        origin="CNSHA", destination="TRMER", customer_id=world.customer_id, incoterm="fob",
        commodity="Household textiles", gross_weight_kg="18500.5"), now=FIXED_NOW)
    rfqs = list(world.session.scalars(select(CarrierRFQ).where(
        CarrierRFQ.quote_request_id == UUID(result["quote_request_id"]))))
    assert len(rfqs) == 2
    carrier_names = list(world.suppliers)
    for rfq in rfqs:
        text = rfq.subject + "\n" + rfq.body
        assert rfq.reference_code in rfq.subject and rfq.reference_code in rfq.body
        assert "Shanghai (CNSHA) -> Mersin (TRMER)" in rfq.subject and "2 x 40HC" in rfq.subject
        for expected in ("Dangerous goods: No", "Commodity: Household textiles", "Gross weight: 18,500.5 kg",
                         "Cargo ready date: 2026-11-20", "Incoterm: FOB", "Please reply by 2026-11-11 12:00 UTC"):
            assert expected in rfq.body
        assert "Secret Customer" not in text and str(world.customer_id) not in text
        assert "USD" not in text  # requested (customer) currency is not shared
        for amount in ("1450", "110", "45", "999.25"):  # seeded/test buy amounts
            assert not re.search(rf"(?<![\w.]){re.escape(amount)}(?![\w.])", text)
        own_name = world.session.get(Supplier, rfq.supplier_id).name
        other_names = [name for name in carrier_names if name != own_name]
        assert not any(name in text for name in other_names)
        assert not any(other.reference_code in text for other in rfqs if other is not rfq)
        assert "rate history" not in text.lower() and "target" not in text.lower()


def test_drafts_render_turkish_location_names(sourcing_world):
    world = sourcing_world
    izmir = Location(name="İzmir Alsancak Limanı", city="İzmir", country_code="TR", location_type="PORT",
                     un_locode="TRIZM")
    world.session.add(izmir)
    world.session.flush()
    world.locations["TRIZM"] = izmir.id
    result = service.start_sourcing(world.session, world.tenant_id, world.request(origin="TRIZM"), now=FIXED_NOW)
    rfq = world.session.scalar(select(CarrierRFQ).where(CarrierRFQ.quote_request_id == UUID(result["quote_request_id"])))
    assert "İzmir Alsancak Limanı (TRIZM) -> Shanghai (CNSHA)" in rfq.subject
    assert "Port of loading (POL): İzmir Alsancak Limanı (TRIZM)" in rfq.body


# --- Outbound interface ------------------------------------------------------------------------------

def test_draft_only_sender_never_sends():
    sender = DraftOnlySender()
    assert isinstance(sender, RFQSender) and sender.name == "draft_only"
    with pytest.raises(SendingDisabled):
        sender.send(SimpleNamespace())


@pytest.mark.parametrize("value", [None, "", "draft_only", " DRAFT_ONLY "])
def test_get_sender_defaults_to_draft_only(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("CARGOAI_RFQ_SENDER", raising=False)
    else:
        monkeypatch.setenv("CARGOAI_RFQ_SENDER", value)
    assert isinstance(get_sender(), DraftOnlySender)


@pytest.mark.parametrize("value", ["smtp", "gmail", "graph"])
def test_unknown_sender_is_configuration_error(monkeypatch, value):
    monkeypatch.setenv("CARGOAI_RFQ_SENDER", value)
    with pytest.raises(SourcingConfigurationError):
        get_sender()


def draft(world, **request_changes):
    result = service.start_sourcing(world.session, world.tenant_id, world.request(**request_changes), now=FIXED_NOW)
    return world.session.scalar(select(CarrierRFQ).where(
        CarrierRFQ.quote_request_id == UUID(result["quote_request_id"])).order_by(CarrierRFQ.reference_code).limit(1))


def test_eml_parses_back(sourcing_world):
    rfq = draft(sourcing_world)
    service.approve_rfq(sourcing_world.session, sourcing_world.tenant_id, rfq.id, now=FIXED_NOW)
    raw = render_eml(rfq, "Ops@Example.com")
    parsed = message_from_bytes(raw, policy=default_policy)
    assert parsed["Message-ID"] == rfq.outbound_message_id
    assert parsed["To"] == rfq.recipient_email and parsed["From"] == "ops@example.com"
    assert parsed["Subject"] == rfq.subject
    assert parsed["X-CargoAI-Reference"] == rfq.reference_code
    assert parsed.get_content().replace("\r\n", "\n") == rfq.body
    assert b"\r\n" in raw  # SMTP line endings


def test_eml_rejects_header_injection(sourcing_world):
    rfq = draft(sourcing_world)
    with pytest.raises(ValueError):
        render_eml(rfq, "ops@example.com\nBcc: victim@example.com")
    rfq_copy = SimpleNamespace(**{key: getattr(rfq, key) for key in ("subject", "body", "outbound_message_id",
                                                                     "reference_code", "approved_at", "created_at")},
                               recipient_email="a@example.com\r\nBcc: b@example.com")
    with pytest.raises(ValueError):
        render_eml(rfq_copy, "ops@example.com")


class FakeSender:
    name = "fake_test_sender"

    def __init__(self):
        self.received = []

    def send(self, rfq):
        self.received.append(rfq)
        return SendResult(channel=self.name, sent_at=FIXED_NOW + timedelta(minutes=5), provider_message_id="fake-1")


def test_fake_sender_receives_immutable_snapshot(sourcing_world):
    world = sourcing_world
    rfq = draft(world)
    service.approve_rfq(world.session, world.tenant_id, rfq.id, now=FIXED_NOW)
    sender = FakeSender()
    assert isinstance(sender, RFQSender)
    detail = service.send_rfq(world.session, world.tenant_id, rfq.id, sender, from_address="ops@example.com")
    [snapshot] = sender.received
    assert snapshot.rfq_id == rfq.id and snapshot.to_address == rfq.recipient_email
    assert snapshot.message_id == rfq.outbound_message_id and snapshot.reference_code == rfq.reference_code
    assert message_from_bytes(snapshot.eml, policy=default_policy)["Message-ID"] == rfq.outbound_message_id
    with pytest.raises(AttributeError):
        snapshot.subject = "changed"
    assert detail["status"] == "SENT" and detail["send_channel"] == "fake_test_sender"
    assert rfq.sent_at == FIXED_NOW + timedelta(minutes=5)


def test_build_outbound_matches_rfq(sourcing_world):
    rfq = draft(sourcing_world)
    outbound = build_outbound(rfq, "ops@example.com")
    assert outbound.body == rfq.body and outbound.subject == rfq.subject and outbound.tenant_id == rfq.tenant_id
