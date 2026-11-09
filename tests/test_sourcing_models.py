from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, StatementError

from conftest import FIXED_NOW
from database.models import CarrierRFQ, QuoteRequest, SupplierLaneCapability
from database.repositories import sourcing_repository as sourcing_repo
from database.repositories import supplier_repository as supplier_repo
from sourcing import config
from sourcing.deadlines import count_overdue, is_overdue, response_due_at
from sourcing.exceptions import SourcingConfigurationError

pytestmark = pytest.mark.usefixtures("no_network")
PHASE1_TABLES = {"supplier_contacts", "supplier_lane_capabilities", "carrier_rfqs"}


def migration_config(connection):
    config_ = Config("alembic.ini")
    config_.attributes["connection"] = connection
    return config_


def quote_request(world, tenant_id, **values):
    return sourcing_repo.create_quote_request(world.session, tenant_id, mode="OCEAN_FCL", **values)


def rfq_values(world, request_id, supplier_id, contact_id, code="CAI-RFQ-ABCDEFGH"):
    return dict(quote_request_id=request_id, supplier_id=supplier_id, supplier_contact_id=contact_id,
                recipient_email="rates@example.com", reference_code=code, outbound_message_id=f"<rfq.{uuid4()}@x.invalid>",
                subject=f"RFQ {code}", body=code, template_version="rfq_ocean_fcl_en_v2",
                response_due_at=FIXED_NOW, selection_metadata={})


# --- B1: schema and migration -------------------------------------------------------------------

def test_migration_downgrade_to_0004_and_upgrade_again(sourcing_engine):
    with sourcing_engine.begin() as connection:
        config_ = migration_config(connection)
        command.downgrade(config_, "0004_management")
        tables = set(inspect(connection).get_table_names())
        assert not PHASE1_TABLES & tables
        assert "carrier_replies" not in tables and "carrier_quote_lines" not in tables
        assert "sourcing_status" not in {c["name"] for c in inspect(connection).get_columns("quote_requests")}
        command.upgrade(config_, "head")
        assert PHASE1_TABLES <= set(inspect(connection).get_table_names())
        columns = {c["name"] for c in inspect(connection).get_columns("quote_requests")}
        assert {"origin_location_id", "sourcing_status", "request_fingerprint", "updated_at"} <= columns
        checks = {c["name"] for c in inspect(connection).get_check_constraints("quote_requests")}
        assert {"ck_quote_requests_rate_mode", "ck_quote_requests_positive_container_count"} <= checks


def test_phase2_tables_not_created(sourcing_engine):
    tables = set(inspect(sourcing_engine).get_table_names())
    assert "carrier_replies" not in tables and "carrier_quote_lines" not in tables


def test_downgrade_refuses_to_discard_rfq_history(sourcing_world, sourcing_engine):
    world = sourcing_world
    supplier = world.carrier(world.tenant_id, "Audit Carrier")
    contact = supplier_repo.list_supplier_contacts(world.session, world.tenant_id, supplier_id=supplier.id)[0]
    request = quote_request(world, world.tenant_id, sourcing_status="RFQ_DRAFTED", request_fingerprint="f" * 64)
    sourcing_repo.create_carrier_rfq(world.session, world.tenant_id, **rfq_values(world, request.id, supplier.id, contact.id))
    world.session.commit()
    with sourcing_engine.begin() as connection:
        with pytest.raises(RuntimeError, match="carrier RFQ history"):
            command.downgrade(migration_config(connection), "0004_management")


def test_cross_tenant_supplier_on_rfq_rejected(sourcing_world):
    world = sourcing_world
    other = world.new_tenant("other")
    foreign = world.carrier(other, "Foreign Carrier")
    own = world.carrier(world.tenant_id, "Own Carrier")
    own_contact = supplier_repo.list_supplier_contacts(world.session, world.tenant_id, supplier_id=own.id)[0]
    request = quote_request(world, world.tenant_id)
    world.session.add(CarrierRFQ(tenant_id=world.tenant_id, **rfq_values(world, request.id, foreign.id, own_contact.id)))
    with pytest.raises(IntegrityError):
        world.session.flush()


def test_rfq_contact_must_belong_to_rfq_supplier(sourcing_world):
    world = sourcing_world
    first = world.carrier(world.tenant_id, "First Carrier", emails=("a@example.com",))
    second = world.carrier(world.tenant_id, "Second Carrier", emails=("b@example.com",))
    second_contact = supplier_repo.list_supplier_contacts(world.session, world.tenant_id, supplier_id=second.id)[0]
    request = quote_request(world, world.tenant_id)
    world.session.add(CarrierRFQ(tenant_id=world.tenant_id, **rfq_values(world, request.id, first.id, second_contact.id)))
    with pytest.raises(IntegrityError):
        world.session.flush()


def test_cross_tenant_contact_supplier_rejected(sourcing_world):
    world = sourcing_world
    other = world.new_tenant("other")
    own = world.carrier(world.tenant_id, "Own Carrier", emails=())
    with pytest.raises(IntegrityError):
        supplier_repo.create_supplier_contact(world.session, other, supplier_id=own.id, email="x@example.com")


@pytest.mark.parametrize("origin", [
    {"origin_location_id": "TRMER", "origin_country_code": "TR"},
    {"origin_location_id": "TRMER", "origin_group_id": "GROUP"},
    {},
])
def test_capability_requires_exactly_one_origin_target(sourcing_world, origin):
    world = sourcing_world
    supplier = world.carrier(world.tenant_id, "Check Carrier")
    values = {key: world.locations[value] if key.endswith("location_id") else
              world.china_group_id if value == "GROUP" else value for key, value in origin.items()}
    world.session.add(SupplierLaneCapability(tenant_id=world.tenant_id, supplier_id=supplier.id, mode="OCEAN_FCL",
                                             destination_country_code="CN", **values))
    with pytest.raises(IntegrityError):
        world.session.flush()


def test_capability_requires_exactly_one_destination_target(sourcing_world):
    world = sourcing_world
    supplier = world.carrier(world.tenant_id, "Check Carrier")
    world.session.add(SupplierLaneCapability(tenant_id=world.tenant_id, supplier_id=supplier.id, mode="OCEAN_FCL",
        origin_country_code="TR", destination_country_code="CN", destination_location_id=world.locations["CNSHA"]))
    with pytest.raises(IntegrityError):
        world.session.flush()


def test_capability_group_must_belong_to_tenant(sourcing_world):
    world = sourcing_world
    other = world.new_tenant("other")
    foreign = world.carrier(other, "Foreign Carrier")
    world.session.add(SupplierLaneCapability(tenant_id=other, supplier_id=foreign.id, mode="OCEAN_FCL",
        origin_group_id=world.china_group_id, destination_country_code="TR"))
    with pytest.raises(IntegrityError):
        world.session.flush()


@pytest.mark.parametrize("values", [{"container_count": 0}, {"sourcing_status": "SENT"}])
def test_quote_request_checks(sourcing_world, values):
    world = sourcing_world
    world.session.add(QuoteRequest(tenant_id=world.tenant_id, mode="OCEAN_FCL", **values))
    with pytest.raises(StatementError):
        world.session.flush()


def test_rfq_reference_code_unique_per_tenant(sourcing_world):
    world = sourcing_world
    supplier = world.carrier(world.tenant_id, "Dup Carrier", emails=("a@example.com", "b@example.com"))
    contacts = supplier_repo.list_supplier_contacts(world.session, world.tenant_id, supplier_id=supplier.id)
    request = quote_request(world, world.tenant_id)
    sourcing_repo.create_carrier_rfq(world.session, world.tenant_id, **rfq_values(world, request.id, supplier.id, contacts[0].id))
    with pytest.raises(IntegrityError):
        sourcing_repo.create_carrier_rfq(world.session, world.tenant_id,
                                         **rfq_values(world, request.id, supplier.id, contacts[1].id))


# --- B2: repositories ---------------------------------------------------------------------------

def test_repository_getters_return_none_for_other_tenant(sourcing_world):
    world = sourcing_world
    other = world.new_tenant("other")
    supplier = world.carrier(world.tenant_id, "Scoped Carrier",
                             capabilities=[{"origin_country_code": "TR", "destination_country_code": "CN"}])
    contact = supplier_repo.list_supplier_contacts(world.session, world.tenant_id, supplier_id=supplier.id)[0]
    capability = supplier_repo.list_lane_capabilities(world.session, world.tenant_id, supplier_id=supplier.id)[0]
    request = quote_request(world, world.tenant_id)
    rfq = sourcing_repo.create_carrier_rfq(world.session, world.tenant_id,
                                           **rfq_values(world, request.id, supplier.id, contact.id))
    session = world.session
    assert supplier_repo.get_supplier(session, world.tenant_id, supplier.id) is supplier
    assert supplier_repo.get_supplier(session, other, supplier.id) is None
    assert supplier_repo.get_supplier_contact(session, other, contact.id) is None
    assert supplier_repo.find_supplier_contact(session, other, supplier.id, contact.email) is None
    assert supplier_repo.get_lane_capability(session, other, capability.id) is None
    assert supplier_repo.find_supplier_by_name(session, other, "Scoped Carrier") is None
    assert supplier_repo.list_supplier_contacts(session, other) == []
    assert supplier_repo.list_lane_capabilities(session, other) == []
    assert supplier_repo.list_rfq_contacts(session, other, [supplier.id]) == []
    assert sourcing_repo.get_quote_request(session, other, request.id) is None
    assert sourcing_repo.get_carrier_rfq(session, other, rfq.id) is None
    assert sourcing_repo.get_carrier_rfq(session, world.tenant_id, rfq.id) is rfq
    assert sourcing_repo.list_carrier_rfqs(session, other) == []
    assert sourcing_repo.rfq_status_counts(session, other, request.id) == {}
    assert sourcing_repo.drafted_supplier_ids(session, other, request.id) == set()


def test_reference_and_message_id_lookups_are_tenant_scoped(sourcing_world):
    world = sourcing_world
    other = world.new_tenant("other")
    supplier = world.carrier(world.tenant_id, "Ref Carrier")
    contact = supplier_repo.list_supplier_contacts(world.session, world.tenant_id, supplier_id=supplier.id)[0]
    request = quote_request(world, world.tenant_id)
    rfq = sourcing_repo.create_carrier_rfq(world.session, world.tenant_id,
                                           **rfq_values(world, request.id, supplier.id, contact.id, "CAI-RFQ-0123ABCD"))
    assert sourcing_repo.get_rfq_by_reference_code(world.session, world.tenant_id, "CAI-RFQ-0123ABCD") is rfq
    assert sourcing_repo.get_rfq_by_reference_code(world.session, other, "CAI-RFQ-0123ABCD") is None
    assert sourcing_repo.reference_code_exists(world.session, other, "CAI-RFQ-0123ABCD") is False
    assert sourcing_repo.get_rfq_by_outbound_message_id(world.session, world.tenant_id, rfq.outbound_message_id) is rfq
    assert sourcing_repo.get_rfq_by_outbound_message_id(world.session, other, rfq.outbound_message_id) is None


@pytest.mark.parametrize("call", [
    lambda s: supplier_repo.get_supplier(s, "not-a-uuid", uuid4()),
    lambda s: supplier_repo.list_rfq_suppliers(s, None),
    lambda s: supplier_repo.list_supplier_contacts(s, str(uuid4())),
    lambda s: supplier_repo.list_rfq_contacts(s, "x", [uuid4()]),
    lambda s: supplier_repo.create_supplier_contact(s, "x", supplier_id=uuid4(), email="a@example.com"),
    lambda s: supplier_repo.create_lane_capability(s, "x", supplier_id=uuid4(), mode="OCEAN_FCL"),
    lambda s: supplier_repo.list_lane_capabilities(s, 1),
    lambda s: sourcing_repo.create_quote_request(s, "x", mode="OCEAN_FCL"),
    lambda s: sourcing_repo.get_quote_request(s, "x", uuid4()),
    lambda s: sourcing_repo.find_open_quote_request(s, "x", "f" * 64),
    lambda s: sourcing_repo.list_sourcing_requests(s, "x"),
    lambda s: sourcing_repo.get_carrier_rfq(s, "x", uuid4()),
    lambda s: sourcing_repo.get_rfq_by_reference_code(s, "x", "CAI-RFQ-ABCDEFGH"),
    lambda s: sourcing_repo.get_rfq_by_outbound_message_id(s, "x", "<a@b>"),
    lambda s: sourcing_repo.list_carrier_rfqs(s, "x"),
    lambda s: sourcing_repo.rfq_status_counts(s, "x", uuid4()),
    lambda s: sourcing_repo.drafted_supplier_ids(s, "x", uuid4()),
])
def test_repositories_require_uuid_tenant(sourcing_session, call):
    with pytest.raises(ValueError):
        call(sourcing_session)


@pytest.mark.parametrize("email,expected", [(" Rates@Example.COM ", "rates@example.com"),
                                            ("a.b+rfq@sub.example.com", "a.b+rfq@sub.example.com")])
def test_contact_email_normalized(email, expected):
    assert supplier_repo.normalize_email(email) == expected


@pytest.mark.parametrize("email", ["", "no-at-sign", "a@b", "a@@example.com", "a b@example.com",
                                   "a@example.com\nBcc: x@example.com", None])
def test_contact_email_rejected(email):
    with pytest.raises(ValueError):
        supplier_repo.normalize_email(email)


def test_open_request_lookup_ignores_closed_requests(sourcing_world):
    world = sourcing_world
    fingerprint = "a" * 64
    quote_request(world, world.tenant_id, sourcing_status="CANCELLED", request_fingerprint=fingerprint)
    assert sourcing_repo.find_open_quote_request(world.session, world.tenant_id, fingerprint) is None
    open_request = quote_request(world, world.tenant_id, sourcing_status="AWAITING_REPLIES", request_fingerprint=fingerprint)
    assert sourcing_repo.find_open_quote_request(world.session, world.tenant_id, fingerprint) is open_request
    with pytest.raises(ValueError):
        sourcing_repo.list_sourcing_requests(world.session, world.tenant_id, limit=0)


# --- Q8: response deadline and overdue flag -------------------------------------------------------

def test_response_due_defaults_to_48_hours(monkeypatch):
    monkeypatch.delenv("CARGOAI_RFQ_RESPONSE_HOURS", raising=False)
    assert response_due_at(FIXED_NOW) == FIXED_NOW + timedelta(hours=48)
    monkeypatch.setenv("CARGOAI_RFQ_RESPONSE_HOURS", "24")
    assert response_due_at(FIXED_NOW) == FIXED_NOW + timedelta(hours=24)
    with pytest.raises(ValueError):
        response_due_at(FIXED_NOW.replace(tzinfo=None))


@pytest.mark.parametrize("name,value", [("CARGOAI_RFQ_RESPONSE_HOURS", "0"), ("CARGOAI_RFQ_RESPONSE_HOURS", "1.5"),
                                        ("CARGOAI_RFQ_MAX_CARRIERS", "-1"), ("CARGOAI_RFQ_MAX_CARRIERS", "500"),
                                        ("CARGOAI_RFQ_MESSAGE_DOMAIN", "bad domain"),
                                        ("CARGOAI_RFQ_MESSAGE_DOMAIN", "x>@evil.example.com")])
def test_invalid_configuration_fails_closed(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(SourcingConfigurationError):
        {"CARGOAI_RFQ_RESPONSE_HOURS": config.response_hours, "CARGOAI_RFQ_MAX_CARRIERS": config.max_carriers,
         "CARGOAI_RFQ_MESSAGE_DOMAIN": config.message_domain}[name]()


@pytest.mark.parametrize("status,offset_hours,overdue", [
    ("APPROVED", 49, True), ("SENT", 49, True), ("SENT", 48, False), ("SENT", 1, False),
    ("DRAFT", 100, False), ("REPLIED", 100, False), ("CANCELLED", 100, False), ("CLOSED", 100, False)])
def test_overdue_is_deterministic(status, offset_hours, overdue):
    rfq = SimpleNamespace(status=status, response_due_at=FIXED_NOW + timedelta(hours=48))
    now = FIXED_NOW + timedelta(hours=offset_hours)
    assert is_overdue(rfq, now) is overdue
    assert count_overdue([rfq, rfq], now) == (2 if overdue else 0)
    with pytest.raises(ValueError):
        is_overdue(rfq, now.replace(tzinfo=None))
