from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from database.models import Rate, Quote, QuoteLine, LocationGroup, LocationGroupMember, ChargeType
from database.repositories.customer_repository import create_customer
from database.repositories.tenant_repository import create_tenant
from database.repositories.rate_repository import (find_candidate_rates, create_rate, create_rate_sheet,
    create_rate_charge, create_rate_sheet_version, list_rates)
from database.seed import seed_demo
from database.session import build_engine
from pricing.models import PricingRequest
from pricing.pricing_engine import price_quote
from pricing.resolvers import resolve_location, resolve_equipment


@pytest.fixture
def session(tmp_path):
    engine = build_engine(f"sqlite:///{(tmp_path / 'commercial.db').as_posix()}")
    config = Config("alembic.ini")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    with Session(engine, expire_on_commit=False) as session:
        yield session
        session.rollback()
    engine.dispose()


@pytest.fixture
def scenario(session):
    seed = seed_demo(session)
    session.commit()
    tenant_id = UUID(seed["tenant_id"])
    request = PricingRequest(tenant_id=tenant_id,
        origin_location_id=resolve_location(session, tenant_id, "Shanghai").id,
        destination_location_id=resolve_location(session, tenant_id, "Ambarli").id,
        equipment_type_id=resolve_equipment(session, tenant_id, "40HC").id,
        container_count=2, effective_date=date(2026, 10, 15), requested_currency="USD")
    return request, list_rates(session, tenant_id)[0]


def reverse_request(request):
    return request.model_copy(update={"origin_location_id": request.destination_location_id,
                                      "destination_location_id": request.origin_location_id})


def test_supplier_and_customer_commercial_types_are_distinct():
    assert set(Rate.__table__.c.commercial_type.type.enums) == {"SPOT", "CONTRACT"}
    assert set(Quote.__table__.c.commercial_type.type.enums) == {"SPOT", "CONTRACT", "CUSTOMER_FIXED"}


def test_forward_lane_is_never_reused_in_reverse(session, scenario):
    request, rate = scenario
    reversed_request = reverse_request(request)
    assert price_quote(session, request).buy_total == Decimal("3165.00")
    assert price_quote(session, reversed_request).status == "NO_RATE_FOUND"
    assert find_candidate_rates(session, request.tenant_id, request.mode,
        reversed_request.origin_location_id, reversed_request.destination_location_id,
        request.equipment_type_id, request.effective_date) == []


def test_reverse_lane_uses_its_own_explicit_price(session, scenario):
    request, rate = scenario
    reversed_request = reverse_request(request)
    sheet = create_rate_sheet(session, request.tenant_id, name="Explicit reverse lane", mode="OCEAN_FCL",
                              source_type="MANUAL", status="ACTIVE")
    reverse = create_rate(session, request.tenant_id, rate_sheet_id=sheet.id, mode="OCEAN_FCL",
        origin_location_id=reversed_request.origin_location_id, destination_location_id=reversed_request.destination_location_id,
        equipment_type_id=request.equipment_type_id, commercial_type="CONTRACT",
        valid_from=date(2026, 10, 1), valid_to=date(2026, 10, 31))
    freight = session.scalar(select(ChargeType).where(ChargeType.canonical_code == "OCEAN_FREIGHT"))
    create_rate_charge(session, request.tenant_id, rate_id=reverse.id, charge_type_id=freight.id,
                       amount=Decimal("700"), currency="USD", basis="PER_CONTAINER")
    assert price_quote(session, request).selected_rate_id == rate.id
    reversed_result = price_quote(session, reversed_request)
    assert reversed_result.selected_rate_id == reverse.id
    assert reversed_result.buy_total == Decimal("1400.00")


def test_group_to_group_lane_is_directional(session, scenario):
    request, rate = scenario
    destinations = LocationGroup(tenant_id=request.tenant_id, name="Destination ports")
    session.add(destinations)
    session.flush()
    session.add(LocationGroupMember(tenant_id=request.tenant_id, location_group_id=destinations.id,
                                    location_id=request.destination_location_id))
    create_rate(session, request.tenant_id, rate_sheet_id=rate.rate_sheet_id, mode="OCEAN_FCL",
        origin_group_id=rate.origin_group_id, destination_group_id=destinations.id,
        equipment_type_id=request.equipment_type_id)
    assert price_quote(session, reverse_request(request)).status == "NO_RATE_FOUND"


def test_customer_fixed_commitment_outlasts_supplier_without_extending_buy_validity(session, scenario):
    request, rate = scenario
    customer = create_customer(session, request.tenant_id, name="Fixed-price customer")
    request = request.model_copy(update={"customer_id": customer.id})
    result = price_quote(session, request, persist=True)
    quote = session.get(Quote, result.quote_id)
    quote.commercial_type = "CUSTOMER_FIXED"
    quote.quote_valid_from = date(2026, 10, 1)
    quote.quote_valid_until = date(2027, 9, 30)
    session.commit()
    assert rate.valid_to == date(2026, 10, 31)
    assert quote.quote_valid_until > rate.valid_to
    assert quote.sell_total == Decimal("3544.80")
    future = request.model_copy(update={"effective_date": date(2026, 11, 15)})
    assert price_quote(session, future).status == "NO_RATE_FOUND"
    assert session.get(Quote, result.quote_id).quote_valid_until == date(2027, 9, 30)
    assert session.scalar(select(QuoteLine.rate_id).where(QuoteLine.quote_id == quote.id)) == rate.id


def test_customer_fixed_is_not_a_supplier_buy_rate(session, scenario):
    request, rate = scenario
    with pytest.raises(StatementError):
        create_rate(session, request.tenant_id, rate_sheet_id=rate.rate_sheet_id, mode="OCEAN_FCL",
            origin_location_id=request.origin_location_id, destination_location_id=request.destination_location_id,
            equipment_type_id=request.equipment_type_id, commercial_type="CUSTOMER_FIXED")


def test_customer_fixed_requires_a_customer(session, scenario):
    request, _ = scenario
    session.add(Quote(tenant_id=request.tenant_id, currency="USD", commercial_type="CUSTOMER_FIXED"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_customer_fixed_customer_must_belong_to_tenant(session, scenario):
    request, _ = scenario
    other = create_tenant(session, name="B", slug="b")
    other_customer = create_customer(session, other.id, name="B customer")
    session.add(Quote(tenant_id=request.tenant_id, customer_id=other_customer.id,
                      currency="USD", commercial_type="CUSTOMER_FIXED"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_quote_validity_alias_and_date_order(session, scenario):
    request, _ = scenario
    quote = Quote(tenant_id=request.tenant_id, currency="USD", valid_until=date(2027, 1, 31))
    session.add(quote)
    session.flush()
    assert quote.quote_valid_until == quote.valid_until == date(2027, 1, 31)
    quote.quote_valid_from = date(2027, 2, 1)
    with pytest.raises(IntegrityError):
        session.flush()


def test_commercial_type_and_optional_notes_preserved_by_version_without_affecting_prices(session, scenario):
    request, rate = scenario
    assert rate.commercial_type == "SPOT"
    fields = {"commercial_type": "CONTRACT", "market_notes": "Market context only",
              "capacity_notes": "Limited space; not a charge", "service_frequency_notes": "Weekly service",
              "disruption_notes": "Possible disruption; do not infer a surcharge"}
    successor = create_rate_sheet_version(session, request.tenant_id, rate.rate_sheet_id, rate_changes={rate.id: fields})
    copied = list_rates(session, request.tenant_id, rate_sheet_id=successor.id)[0]
    session.commit()
    session.expire_all()
    for name, value in fields.items():
        assert getattr(session.get(Rate, copied.id), name) == value
    result = price_quote(session, request)
    assert result.buy_total == Decimal("3165.00")
    assert result.sell_total == Decimal("3544.80")
    assert result.selected_rate_id == copied.id
    assert session.get(Rate, rate.id).commercial_type == "SPOT"


def test_migration_preserves_old_quote_dates_and_related_lines(tmp_path):
    engine = build_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    ids = {name: uuid4().hex for name in ("tenant", "quote", "line")}
    config = Config("alembic.ini")
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0002_pricing")
            connection.execute(text("INSERT INTO tenants (id, name, slug) VALUES (:tenant, 'Legacy', 'legacy')"), ids)
            connection.execute(text("INSERT INTO quotes (id, tenant_id, currency, valid_until) VALUES (:quote, :tenant, 'USD', '2027-01-31')"), ids)
            connection.execute(text("INSERT INTO quote_lines (id, tenant_id, quote_id, description, quantity, unit_amount, total_amount, currency, basis) VALUES (:line, :tenant, :quote, 'Legacy line', 1, 10, 10, 'USD', 'FLAT')"), ids)
            command.upgrade(config, "head")
            expiry, start, kind = connection.execute(text("SELECT quote_valid_until, quote_valid_from, commercial_type FROM quotes")).one()
            assert str(expiry) == "2027-01-31"
            assert start is None and kind == "SPOT"
            assert connection.scalar(text("SELECT quote_id FROM quote_lines")) == ids["quote"]
            command.downgrade(config, "0002_pricing")
            assert str(connection.scalar(text("SELECT valid_until FROM quotes"))) == "2027-01-31"
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def test_downgrade_does_not_silently_drop_fixed_commitments(session, scenario):
    request, _ = scenario
    customer = create_customer(session, request.tenant_id, name="Customer")
    session.add(Quote(tenant_id=request.tenant_id, customer_id=customer.id, currency="USD", commercial_type="CUSTOMER_FIXED"))
    session.commit()
    config = Config("alembic.ini")
    with session.get_bind().begin() as connection:
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="CUSTOMER_FIXED"):
            command.downgrade(config, "0002_pricing")
