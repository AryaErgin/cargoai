from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, func
from sqlalchemy import event
from sqlalchemy.orm import Session

from database.models import (Tenant, Location, LocationAlias, LocationGroup, LocationGroupMember, EquipmentType,
                             EquipmentAlias, ChargeType, Rate, Quote, QuoteLine, ExchangeRate)
from database.repositories.tenant_repository import create_tenant
from database.repositories.customer_repository import create_customer
from database.repositories.pricing_rule_repository import create_pricing_rule
from database.repositories.rate_repository import (create_rate, create_rate_sheet, create_rate_charge,
    create_rate_sheet_version, list_rates, list_rate_charges)
from database.repositories.exchange_rate_repository import create_exchange_rate
from database.seed import seed_demo
from database.session import build_engine
from pricing.pricing_engine import price_quote
from pricing.models import PricingRequest
from pricing.resolvers import resolve_location, resolve_equipment
from pricing.exceptions import AmbiguousReference, InvalidPricingRequest, PricingError
from pricing.money import money

FIXED_TIME = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.fixture
def session(tmp_path):
    engine = build_engine(f"sqlite:///{(tmp_path / 'pricing.db').as_posix()}")
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
    origin = resolve_location(session, tenant_id, "Shanghai")
    destination = resolve_location(session, tenant_id, "Ambarli")
    equipment = resolve_equipment(session, tenant_id, "40HC")
    request = PricingRequest(tenant_id=tenant_id, origin_location_id=origin.id, destination_location_id=destination.id,
        equipment_type_id=equipment.id, container_count=2, effective_date=date(2026, 10, 15), requested_currency="USD")
    rate = list_rates(session, tenant_id)[0]
    return request, rate


def new_rate(session, request, *, origin_group_id=None, destination_group_id=None, priority=0,
             valid_from=date(2026, 10, 1), valid_to=date(2026, 10, 31), amount="1450", **values):
    sheet = create_rate_sheet(session, request.tenant_id, name="Test rates", mode="OCEAN_FCL",
        source_type="MANUAL", status="ACTIVE", valid_from=valid_from, valid_to=valid_to)
    rate = create_rate(session, request.tenant_id, rate_sheet_id=sheet.id, mode="OCEAN_FCL",
        origin_location_id=None if origin_group_id else request.origin_location_id, origin_group_id=origin_group_id,
        destination_location_id=None if destination_group_id else request.destination_location_id,
        destination_group_id=destination_group_id, equipment_type_id=request.equipment_type_id,
        valid_from=valid_from, valid_to=valid_to, priority=priority, created_at=FIXED_TIME, **values)
    charge_type = session.scalar(select(ChargeType).where(ChargeType.canonical_code == "OCEAN_FREIGHT"))
    create_rate_charge(session, request.tenant_id, rate_id=rate.id, charge_type_id=charge_type.id,
                       amount=Decimal(amount), currency="USD", basis="PER_CONTAINER")
    return rate


def add_charge(session, request, rate, *, amount="10", currency="USD", basis="FLAT", code="BAF", **values):
    charge_type = session.scalar(select(ChargeType).where(ChargeType.canonical_code == code))
    return create_rate_charge(session, request.tenant_id, rate_id=rate.id, charge_type_id=charge_type.id,
                             amount=Decimal(amount), currency=currency, basis=basis, **values)


def add_rule(session, request, *, value="20", rule_type="PERCENT_MARKUP", **values):
    return create_pricing_rule(session, request.tenant_id, name="Test rule", rule_type=rule_type,
                               value=Decimal(value), **values)


def test_demo_quote_decimal_arithmetic(session, scenario):
    request, rate = scenario
    result = price_quote(session, request)
    assert result.status == "PRICED"
    assert result.buy_total == Decimal("3165.00")
    assert result.markup_amount == Decimal("379.80")
    assert result.sell_total == Decimal("3544.80")
    assert result.final_margin_amount == Decimal("379.80")
    assert result.margin_percent == Decimal("10.71")
    assert {line.charge_type: line.converted_total for line in result.line_items} == {
        "OCEAN_FREIGHT": Decimal("2900.00"), "DESTINATION_THC": Decimal("220.00"), "DOCUMENTATION": Decimal("45.00")}
    assert result.selected_rate_id == rate.id
    assert result.quote_id is None
    assert session.scalar(select(func.count()).select_from(Quote)) == 0


def test_exact_exact_beats_group_exact(session, scenario):
    request, _ = scenario
    exact = new_rate(session, request, priority=-10)
    result = price_quote(session, request)
    assert result.selected_rate_id == exact.id
    assert result.rate_selection_metadata["specificity_level"] == 1


@pytest.mark.parametrize("origin_group,destination_group,level", [(False, True, 2), (True, False, 3), (True, True, 4)])
def test_group_specificity_levels(session, scenario, origin_group, destination_group, level):
    request, demo_rate = scenario
    destination = LocationGroup(tenant_id=request.tenant_id, name="Destination group")
    session.add(destination)
    session.flush()
    session.add(LocationGroupMember(tenant_id=request.tenant_id, location_group_id=destination.id,
                                    location_id=request.destination_location_id))
    row = new_rate(session, request, origin_group_id=demo_rate.origin_group_id if origin_group else None,
                   destination_group_id=destination.id if destination_group else None, priority=10)
    result = price_quote(session, request)
    if level == 4:  # The seed's group/exact outranks group/group regardless of priority.
        assert result.selected_rate_id == demo_rate.id
    else:
        assert result.selected_rate_id == row.id
        assert result.rate_selection_metadata["specificity_level"] == level


def test_exact_group_beats_group_group(session, scenario):
    request, demo_rate = scenario
    destination = LocationGroup(tenant_id=request.tenant_id, name="Destination group")
    session.add(destination)
    session.flush()
    session.add(LocationGroupMember(tenant_id=request.tenant_id, location_group_id=destination.id,
                                    location_id=request.destination_location_id))
    new_rate(session, request, origin_group_id=demo_rate.origin_group_id, destination_group_id=destination.id, priority=100)
    exact_group = new_rate(session, request, destination_group_id=destination.id)
    assert price_quote(session, request).selected_rate_id == exact_group.id


def test_rate_priority_wins(session, scenario):
    request, _ = scenario
    new_rate(session, request, priority=1)
    winner = new_rate(session, request, priority=2)
    assert price_quote(session, request).selected_rate_id == winner.id


def test_narrower_validity_wins(session, scenario):
    request, _ = scenario
    new_rate(session, request)
    narrower = new_rate(session, request, valid_from=date(2026, 10, 10), valid_to=date(2026, 10, 20))
    assert price_quote(session, request).selected_rate_id == narrower.id


def test_more_recent_validity_wins(session, scenario):
    request, _ = scenario
    new_rate(session, request, valid_from=date(2026, 10, 1), valid_to=date(2026, 10, 20))
    recent = new_rate(session, request, valid_from=date(2026, 10, 5), valid_to=date(2026, 10, 24))
    assert price_quote(session, request).selected_rate_id == recent.id


def test_rate_version_wins_and_history_remains(session, scenario):
    request, rate = scenario
    successor = create_rate_sheet_version(session, request.tenant_id, rate.rate_sheet_id)
    copied = list_rates(session, request.tenant_id, rate_sheet_id=successor.id)[0]
    assert price_quote(session, request).selected_rate_id == copied.id
    assert len(list_rates(session, request.tenant_id)) == 2


def test_newest_rate_creation_final_tiebreak(session, scenario):
    request, _ = scenario
    new_rate(session, request)
    winner = new_rate(session, request)
    # The new row is still uncommitted, but already flushed; create a distinct
    # timestamp directly at insertion rather than changing persisted history.
    third = create_rate(session, request.tenant_id, rate_sheet_id=winner.rate_sheet_id,
        mode="OCEAN_FCL", origin_location_id=request.origin_location_id,
        destination_location_id=request.destination_location_id, equipment_type_id=request.equipment_type_id,
        valid_from=date(2026, 10, 1), valid_to=date(2026, 10, 31), created_at=datetime(2026, 10, 2, tzinfo=timezone.utc))
    add_charge(session, request, third)
    assert price_quote(session, request).selected_rate_id == third.id


def test_ambiguous_rates_fail_without_uuid_tiebreak(session, scenario):
    request, _ = scenario
    first, second = new_rate(session, request), new_rate(session, request)
    result = price_quote(session, request, persist=True)
    assert result.status == "AMBIGUOUS_RATE"
    assert set(result.error_metadata["candidate_ids"]) == {str(first.id), str(second.id)}
    assert session.scalar(select(func.count()).select_from(Quote)) == 0


@pytest.mark.parametrize("effective_date,status", [(date(2026, 9, 30), "NO_RATE_FOUND"),
    (date(2026, 10, 1), "PRICED"), (date(2026, 10, 31), "PRICED"), (date(2026, 11, 1), "NO_RATE_FOUND")])
def test_rate_validity_boundaries(session, scenario, effective_date, status):
    request, _ = scenario
    result = price_quote(session, request.model_copy(update={"effective_date": effective_date}))
    assert result.status == status


def test_expired_future_inactive_rates_rejected(session, scenario):
    request, rate = scenario
    new_rate(session, request, valid_to=date(2026, 10, 10), amount="1")
    new_rate(session, request, valid_from=date(2026, 10, 20), amount="1")
    new_rate(session, request, is_active=False, amount="1")
    result = price_quote(session, request)
    assert result.selected_rate_id == rate.id
    reasons = [reason for item in result.rate_selection_metadata["rejected_candidates"] for reason in item["reasons"]]
    assert reasons.count("rate_outside_validity") == 2
    assert "inactive_rate" in reasons


def test_no_equipment_fallback(session, scenario):
    request, _ = scenario
    equipment = resolve_equipment(session, request.tenant_id, "20GP")
    assert price_quote(session, request.model_copy(update={"equipment_type_id": equipment.id})).status == "NO_RATE_FOUND"


def test_flat_and_optional_charges(session, scenario):
    request, rate = scenario
    add_charge(session, request, rate, amount="10", basis="FLAT")
    optional = add_charge(session, request, rate, amount="900", mandatory=False)
    result = price_quote(session, request)
    assert result.buy_total == Decimal("3175.00")
    assert result.optional_charges_available[0]["rate_charge_id"] == str(optional.id)
    assert optional.id not in {line.rate_charge_id for line in result.line_items}


@pytest.mark.parametrize("base,expected", [("FREIGHT_SUBTOTAL", "3455.00"), ("BUY_SUBTOTAL", "3481.50")])
def test_percentage_charges_explicit_noncompounding_base(session, scenario, base, expected):
    request, rate = scenario
    add_charge(session, request, rate, amount="10", basis="PERCENTAGE", percentage_base=base)
    result = price_quote(session, request)
    assert result.buy_total == Decimal(expected)
    assert next(line for line in result.line_items if line.basis == "PERCENTAGE").percentage_base == base


def test_percentages_do_not_include_each_other(session, scenario):
    request, rate = scenario
    for _ in range(2):
        add_charge(session, request, rate, amount="10", basis="PERCENTAGE", percentage_base="BUY_SUBTOTAL")
    assert price_quote(session, request).buy_total == Decimal("3798.00")


def test_percentage_without_base_fails(session, scenario):
    request, rate = scenario
    add_charge(session, request, rate, basis="PERCENTAGE")
    with pytest.raises(PricingError, match="explicit"):
        price_quote(session, request)


def test_unsupported_mandatory_charge_fails(session, scenario):
    request, rate = scenario
    add_charge(session, request, rate, basis="PER_KG")
    with pytest.raises(PricingError, match="Unsupported mandatory"):
        price_quote(session, request)


def test_charge_validity_equipment_and_bounds(session, scenario):
    request, rate = scenario
    add_charge(session, request, rate, amount="1000", valid_from=date(2026, 11, 1))
    add_charge(session, request, rate, amount="1000", equipment_type_id=resolve_equipment(session, request.tenant_id, "20GP").id)
    add_charge(session, request, rate, amount="10", basis="PER_CONTAINER", minimum_amount=Decimal("25"))
    assert price_quote(session, request).buy_total == Decimal("3190.00")


def test_multiple_currencies(session, scenario):
    request, rate = scenario
    add_charge(session, request, rate, amount="10", currency="EUR")
    result = price_quote(session, request)
    assert result.buy_total == Decimal("3176.11")
    converted = next(line for line in result.line_items if line.source_currency == "EUR")
    assert converted.fx_rate_id is not None
    assert converted.fx_rate_value == Decimal("1.11111111")


def test_same_currency_and_valid_fx(session, scenario):
    request, _ = scenario
    result = price_quote(session, request)
    assert result.fx_conversions[0]["rate_id"] is None
    assert result.fx_conversions[0]["rate"] == Decimal("1")
    euro = price_quote(session, request.model_copy(update={"requested_currency": "EUR"}))
    assert euro.buy_total == Decimal("2848.50")
    assert euro.sell_total == Decimal("3190.32")
    assert euro.fx_conversions[0]["rate"] == Decimal("0.90000000")


def test_missing_fx_and_no_cross_conversion(session, scenario):
    request, _ = scenario
    create_exchange_rate(session, request.tenant_id, base_currency="EUR", quote_currency="GBP", rate=Decimal("0.8"),
                        effective_from=date(2026, 10, 1))
    result = price_quote(session, request.model_copy(update={"requested_currency": "GBP"}))
    assert result.status == "MISSING_FX"
    assert result.buy_total is None


def test_no_implicit_inverse_fx(session, scenario):
    request, _ = scenario
    create_exchange_rate(session, request.tenant_id, base_currency="GBP", quote_currency="USD", rate=Decimal("1.2"),
                        effective_from=date(2026, 10, 1))
    assert price_quote(session, request.model_copy(update={"requested_currency": "GBP"})).status == "MISSING_FX"


@pytest.mark.parametrize("day,status", [(9, "MISSING_FX"), (10, "PRICED"), (20, "PRICED"), (21, "MISSING_FX")])
def test_fx_inclusive_validity_boundaries(session, scenario, day, status):
    request, _ = scenario
    create_exchange_rate(session, request.tenant_id, base_currency="USD", quote_currency="GBP", rate=Decimal("0.8"),
                        effective_from=date(2026, 10, 10), effective_to=date(2026, 10, 20))
    assert price_quote(session, request.model_copy(update={"requested_currency": "GBP", "effective_date": date(2026, 10, day)})).status == status


def test_fx_effective_dates_and_tenant_isolation(session, scenario):
    request, _ = scenario
    other = create_tenant(session, name="B", slug="b")
    create_exchange_rate(session, other.id, base_currency="USD", quote_currency="GBP", rate=Decimal("0.8"),
                        effective_from=date(2026, 10, 1))
    assert price_quote(session, request.model_copy(update={"requested_currency": "GBP"})).status == "MISSING_FX"
    create_exchange_rate(session, request.tenant_id, base_currency="USD", quote_currency="GBP", rate=Decimal("0.8"),
                        effective_from=date(2026, 10, 20))
    assert price_quote(session, request.model_copy(update={"requested_currency": "GBP"})).status == "MISSING_FX"


def test_overlapping_fx_is_clear_failure(session, scenario):
    request, _ = scenario
    create_exchange_rate(session, request.tenant_id, base_currency="USD", quote_currency="EUR", rate=Decimal("0.91"),
                        effective_from=date(2026, 10, 10), effective_to=date(2026, 10, 20))
    result = price_quote(session, request.model_copy(update={"requested_currency": "EUR"}))
    assert result.status == "MISSING_FX"
    assert len(result.error_metadata["matched_fx_ids"]) == 2


def test_central_decimal_rounding():
    assert money(Decimal("1.005")) == Decimal("1.01")
    assert money(Decimal("-1.005")) == Decimal("-1.01")
    with pytest.raises(ValueError):
        money(1.005)


@pytest.mark.parametrize("tier", [1, 2, 3, 4, 5, 6, 7, 8])
def test_rule_specificity_tiers(session, scenario, tier):
    request, _ = scenario
    fields = {"priority": 1}
    if tier <= 4:
        customer = create_customer(session, request.tenant_id, name="Customer")
        request = request.model_copy(update={"customer_id": customer.id})
        fields["customer_id"] = customer.id
    lane = tier in (1, 2, 5, 6)
    equipment = tier in (1, 3, 5, 7)
    if lane:
        fields.update(origin_location_id=request.origin_location_id, destination_location_id=request.destination_location_id)
    if equipment:
        fields["equipment_type_id"] = request.equipment_type_id
    rule = add_rule(session, request, **fields)
    result = price_quote(session, request)
    assert result.applied_pricing_rules[0]["rule_id"] == str(rule.id)
    assert result.applied_pricing_rules[0]["specificity_level"] == tier
    assert result.markup_amount == Decimal("633.00")


def test_customer_override_beats_high_priority_tenant_lane_equipment(session, scenario):
    request, _ = scenario
    customer = create_customer(session, request.tenant_id, name="Customer")
    request = request.model_copy(update={"customer_id": customer.id})
    add_rule(session, request, priority=999, origin_location_id=request.origin_location_id, equipment_type_id=request.equipment_type_id)
    rule = add_rule(session, request, customer_id=customer.id, value="5")
    assert price_quote(session, request).applied_pricing_rules[0]["rule_id"] == str(rule.id)


def test_rule_priority_and_ambiguity(session, scenario):
    request, _ = scenario
    rule = add_rule(session, request, priority=2)
    assert price_quote(session, request).applied_pricing_rules[0]["rule_id"] == str(rule.id)
    add_rule(session, request, priority=2)
    result = price_quote(session, request)
    assert result.status == "AMBIGUOUS_PRICING_RULE"


def test_fixed_and_percent_markups_compete_not_stack(session, scenario):
    request, _ = scenario
    add_rule(session, request, rule_type="FIXED_MARKUP", value="100", currency="USD")
    assert price_quote(session, request).status == "AMBIGUOUS_PRICING_RULE"


@pytest.mark.parametrize("floor,expected", [("250", "3544.80"), ("500", "3665.00")])
def test_minimum_margin(session, scenario, floor, expected):
    request, _ = scenario
    add_rule(session, request, rule_type="MINIMUM_MARGIN", value=floor, currency="USD")
    assert price_quote(session, request).sell_total == Decimal(expected)


def test_discount_after_markup_and_floor(session, scenario):
    request, _ = scenario
    add_rule(session, request, rule_type="MINIMUM_MARGIN", value="500", currency="USD")
    add_rule(session, request, rule_type="DISCOUNT", value="10")
    result = price_quote(session, request)
    assert result.discount_amount == Decimal("366.50")
    assert result.sell_total == Decimal("3298.50")
    assert result.final_margin_amount == Decimal("133.50")


def test_fixed_rule_fx_and_missing_currency(session, scenario):
    request, _ = scenario
    add_rule(session, request, rule_type="FIXED_MARKUP", value="10", currency="EUR", priority=1)
    assert price_quote(session, request).sell_total == Decimal("3176.11")
    add_rule(session, request, rule_type="MINIMUM_MARGIN", value="100")
    with pytest.raises(PricingError, match="explicit currency"):
        price_quote(session, request)


def test_inapplicable_rules_are_filtered(session, scenario):
    request, _ = scenario
    for fields in ({"valid_from": date(2026, 11, 1)}, {"is_active": False}, {"mode": "ROAD_FTL"},
                   {"equipment_type_id": resolve_equipment(session, request.tenant_id, "20GP").id},
                   {"origin_location_id": resolve_location(session, request.tenant_id, "Ningbo").id}):
        add_rule(session, request, priority=999, **fields)
    assert price_quote(session, request).markup_amount == Decimal("379.80")


def test_rule_group_matches(session, scenario):
    request, rate = scenario
    rule = add_rule(session, request, origin_group_id=rate.origin_group_id)
    assert price_quote(session, request).applied_pricing_rules[0]["rule_id"] == str(rule.id)


def test_multitenant_identical_lane_isolation(session, scenario):
    request_a, rate_a = scenario
    tenant_b = create_tenant(session, name="Company B", slug="company-b")
    request_b = request_a.model_copy(update={"tenant_id": tenant_b.id})
    rate_b = new_rate(session, request_b, amount="1700")
    add_rule(session, request_b, value="5")
    a, b = price_quote(session, request_a), price_quote(session, request_b)
    assert a.selected_rate_id == rate_a.id
    assert b.selected_rate_id == rate_b.id
    assert a.buy_total == Decimal("3165.00")
    assert b.buy_total == Decimal("3400.00")
    assert b.markup_amount == Decimal("170.00")
    customer = create_customer(session, tenant_b.id, name="B only")
    with pytest.raises(InvalidPricingRequest, match="Customer"):
        price_quote(session, request_a.model_copy(update={"customer_id": customer.id}))


def test_persistence_and_immutable_audit_after_new_version(session, scenario):
    request, rate = scenario
    result = price_quote(session, request, persist=True)
    session.commit()
    stored = session.get(Quote, result.quote_id)
    original_snapshot = stored.calculation_json
    lines = list(session.scalars(select(QuoteLine).where(QuoteLine.tenant_id == request.tenant_id, QuoteLine.quote_id == stored.id)))
    assert len(lines) == 3
    assert all(line.rate_id == rate.id and line.rate_charge_id is not None for line in lines)
    assert sum((line.total_amount for line in lines), Decimal("0")) == result.buy_total
    charge = next(c for c in list_rate_charges(session, request.tenant_id, rate.id) if c.amount == Decimal("1450"))
    create_rate_sheet_version(session, request.tenant_id, rate.rate_sheet_id, charge_changes={charge.id: {"amount": Decimal("1700")}})
    session.commit()
    assert price_quote(session, request).buy_total == Decimal("3665.00")
    session.expire_all()
    reloaded = session.get(Quote, result.quote_id)
    assert reloaded.buy_total == Decimal("3165.00")
    assert reloaded.calculation_json == original_snapshot
    assert reloaded.calculation_json["result"]["sell_total"] == "3544.80"


def test_persistence_is_atomic_on_line_failure(session, scenario):
    request, _ = scenario
    def reject_line(session, context, instances):
        if any(isinstance(row, QuoteLine) for row in session.new):
            raise ValueError("simulated line failure")
    event.listen(session, "before_flush", reject_line)
    try:
        with pytest.raises(ValueError, match="simulated"):
            price_quote(session, request, persist=True)
    finally:
        event.remove(session, "before_flush", reject_line)
    assert session.scalar(select(func.count()).select_from(Quote)) == 0


def test_percentage_fx_and_audit_round_trip(session, scenario):
    request, rate = scenario
    add_charge(session, request, rate, amount="10", basis="PERCENTAGE", percentage_base="FREIGHT_SUBTOTAL", currency="EUR")
    result = price_quote(session, request, persist=True)
    session.commit()
    assert result.buy_total == Decimal("3455.00")
    percentage = next(line for line in result.line_items if line.basis == "PERCENTAGE")
    assert percentage.converted_total == Decimal("290.00")
    assert percentage.fx_rate_id is not None
    snapshot = session.get(Quote, result.quote_id).calculation_json
    assert snapshot["result"]["fx_conversions"]
    assert snapshot["result"]["applied_pricing_rules"][0]["source_value"] == "12.000000"


def test_mutated_invalid_request_cannot_skip_validation(session, scenario):
    request, _ = scenario
    with pytest.raises(InvalidPricingRequest, match="Invalid structured"):
        price_quote(session, request.model_copy(update={"container_count": 0}))
    with pytest.raises(InvalidPricingRequest, match="structured PricingRequest"):
        price_quote(session, request.model_dump())


def test_negative_charge_bounds_rejected(session, scenario):
    request, rate = scenario
    add_charge(session, request, rate, maximum_amount=Decimal("-1"))
    with pytest.raises(PricingError, match="bounds"):
        price_quote(session, request)


def test_unqualified_rate_sheets_rejected(session, scenario):
    request, demo_rate = scenario
    sheet = create_rate_sheet(session, request.tenant_id, name="Draft", mode="OCEAN_FCL", source_type="MANUAL")
    create_rate(session, request.tenant_id, rate_sheet_id=sheet.id, mode="OCEAN_FCL", priority=999,
        origin_location_id=request.origin_location_id, destination_location_id=request.destination_location_id,
        equipment_type_id=request.equipment_type_id)
    result = price_quote(session, request)
    assert result.selected_rate_id == demo_rate.id
    assert "inapplicable_rate_sheet" in result.rate_selection_metadata["rejected_candidates"][0]["reasons"]


def test_resolver_order_ambiguity_and_equipment_aliases(session, scenario):
    request, _ = scenario
    session.add_all([LocationAlias(location_id=request.origin_location_id, alias="Port"),
        LocationAlias(tenant_id=request.tenant_id, location_id=request.destination_location_id, alias="Port")])
    session.flush()
    assert resolve_location(session, request.tenant_id, "port").id == request.destination_location_id
    assert resolve_equipment(session, request.tenant_id, "40HQ").id == request.equipment_type_id
    session.add(LocationAlias(tenant_id=request.tenant_id, location_id=request.origin_location_id, alias="Port"))
    session.flush()
    with pytest.raises(AmbiguousReference):
        resolve_location(session, request.tenant_id, "Port")
    with pytest.raises(InvalidPricingRequest):
        resolve_location(session, request.tenant_id, "unrecognized")


@pytest.mark.parametrize("change", [{"container_count": 0}, {"container_count": 1.5}, {"container_count": True}, {"mode": "ROAD_FTL"}])
def test_malformed_domain_request(scenario, change):
    request, _ = scenario
    with pytest.raises(ValidationError):
        PricingRequest(**(request.model_dump() | change))


def test_dg_not_silently_priced(session, scenario):
    request, _ = scenario
    with pytest.raises(InvalidPricingRequest, match="dangerous goods"):
        price_quote(session, request.model_copy(update={"dangerous_goods": True}))


def api_payload(request, **changes):
    return {"tenant_id": str(request.tenant_id), "effective_date": request.effective_date.isoformat(),
        "requested_currency": "USD", "rfq": {"origin": "Shanghai", "destination": "Ambarli",
        "container_type": "40HC", "container_count": 2, "dangerous_goods": False}, **changes}


@pytest.fixture
def client(session, scenario, monkeypatch):
    import api.main as api
    monkeypatch.setattr(api, "get_engine", lambda: session.get_bind())
    import api.lookups as lookups
    monkeypatch.setattr(lookups, "get_engine", lambda: session.get_bind())
    monkeypatch.setenv("CARGOAI_LOCAL_DEMO", "1")
    monkeypatch.setenv("CARGOAI_DEMO_TENANT_ID", str(scenario[0].tenant_id))
    return TestClient(api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def test_quote_api_success_and_persist(session, scenario, client):
    request, _ = scenario
    session.commit()
    response = client.post("/quote/spot", json=api_payload(request, persist=True))
    assert response.status_code == 200
    assert "buy_total" not in response.json()
    assert response.json()["sell_total"] == "3544.80"
    assert response.json()["quote_id"] is not None


@pytest.mark.parametrize("change,status,code", [
    ({"effective_date": "2026-11-01"}, 422, "NO_RATE_FOUND"),
    ({"requested_currency": "GBP"}, 422, "MISSING_FX"),
])
def test_quote_api_domain_failures(scenario, client, change, status, code):
    request, _ = scenario
    response = client.post("/quote/spot", json=api_payload(request, **change))
    assert response.status_code == status
    assert response.json()["detail"]["status"] == code


@pytest.mark.parametrize("ambiguity", ["rate", "rule"])
def test_quote_api_ambiguity(session, scenario, client, ambiguity):
    request, _ = scenario
    if ambiguity == "rate":
        new_rate(session, request)
        new_rate(session, request)
    else:
        add_rule(session, request)
    session.commit()
    response = client.post("/quote/spot", json=api_payload(request))
    assert response.status_code == 409
    assert response.json()["detail"]["status"].startswith("AMBIGUOUS_")


def test_quote_api_malformed_and_no_free_text(scenario, client):
    request, _ = scenario
    payload = api_payload(request)
    payload["rfq"]["container_count"] = 0
    assert client.post("/quote/spot", json=payload).status_code == 422
    assert client.post("/quote/spot", json={"tenant_id": str(request.tenant_id), "text": "RFQ text"}).status_code == 422


def reviewed_payload(request, **changes):
    return {**request.model_dump(mode="json", exclude={"tenant_id"}), "dangerous_goods": False, **changes}


@pytest.mark.parametrize("quantity,buy,sell", [(1, "1605.00", "1797.60"),
    (2, "3165.00", "3544.80"), (3, "4725.00", "5292.00"), (10, "15645.00", "17522.40")])
def test_mocked_extract_review_quote(session, scenario, client, monkeypatch, quantity, buy, sell):
    import api.main as api
    request, rate = scenario
    extracted = {"origin": "Shanghai", "destination": "Ambarli", "container_type": "40HQ",
                 "container_count": quantity, "dangerous_goods": False}
    monkeypatch.setattr(api, "parse_spot_rfq", lambda text: extracted)
    parsed = client.post("/parse/spot", json={"text": "Synthetic RFQ only"}).json()["result"]
    choices = client.get("/quote/lookups").json()
    payload = reviewed_payload(request, container_count=parsed["container_count"])
    for field, kind, key in [("origin_location_id", "location", "origin"),
                              ("destination_location_id", "location", "destination"),
                              ("equipment_type_id", "equipment", "container_type")]:
        payload[field] = client.get("/quote/lookups/resolve", params={"kind": kind, "value": parsed[key]}).json()["id"]
    response = client.post("/quote/spot", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["sell_total"] == sell
    assert sum(Decimal(line["sell_amount"]) for line in result["charges"]) == Decimal(sell)
    assert result["valid_from"] == "2026-10-01" and result["valid_to"] == "2026-10-31"
    assert result["selected_rate_id"] == str(rate.id) and result["demo_data"]
    assert not {"buy_total", "markup_amount", "supplier_id", "applied_pricing_rules", "line_items"} & result.keys()
    internal = price_quote(session, request.model_copy(update={"container_count": quantity}))
    assert internal.buy_total == Decimal(buy) and internal.sell_total == Decimal(sell)
    assert all(row["label"] in {"20GP", "40GP", "40HC"} for row in choices["equipment"])


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, "2", None])
def test_review_invalid_quantity(scenario, client, quantity):
    assert client.post("/quote/spot", json=reviewed_payload(scenario[0], container_count=quantity)).status_code == 422


@pytest.mark.parametrize("changes,code", [({"effective_date": "2026-11-01"}, "NO_RATE_FOUND"),
    ({"requested_currency": "GBP"}, "MISSING_FX"), ({"dangerous_goods": True}, "INVALID_REQUEST")])
def test_review_domain_errors(scenario, client, changes, code):
    response = client.post("/quote/spot", json=reviewed_payload(scenario[0], **changes))
    assert response.status_code == 422 and response.json()["detail"]["status"] == code


def test_review_unavailable_route_and_unsupported_equipment(session, scenario, client):
    request, _ = scenario
    mersin = resolve_location(session, request.tenant_id, "Mersin")
    unsupported = resolve_equipment(session, request.tenant_id, "40OT")
    for changes, code in [({"destination_location_id": str(mersin.id)}, "NO_RATE_FOUND"),
                          ({"equipment_type_id": str(unsupported.id)}, "INVALID_REQUEST")]:
        response = client.post("/quote/spot", json=reviewed_payload(request, **changes))
        assert response.status_code == 422 and response.json()["detail"]["status"] == code
    assert client.post("/quote/spot", json=reviewed_payload(request, dangerous_goods=None)).status_code == 422


def test_reference_ambiguity_and_company_isolation(session, scenario, client):
    request, _ = scenario
    other = create_tenant(session, name="Other", slug="other")
    customer = create_customer(session, other.id, name="Private customer")
    session.add_all([LocationAlias(tenant_id=request.tenant_id, alias="Ambiguous", location_id=request.origin_location_id),
                     LocationAlias(tenant_id=request.tenant_id, alias="Ambiguous", location_id=request.destination_location_id),
                     LocationAlias(tenant_id=other.id, alias="Private alias", location_id=request.origin_location_id)])
    session.commit()
    response = client.get("/quote/lookups/resolve", params={"kind": "location", "value": "Ambiguous"})
    assert response.status_code == 409 and response.json()["detail"]["status"] == "AMBIGUOUS_REFERENCE"
    assert client.get("/quote/lookups/resolve", params={"kind": "location", "value": "Shangha"}).status_code == 422
    assert client.get("/quote/lookups/resolve", params={"kind": "location", "value": "Private alias"}).status_code == 422
    assert not client.get("/quote/lookups").json()["customers"]
    assert client.post("/quote/spot", json=reviewed_payload(request, tenant_id=str(other.id))).status_code == 403
    assert client.post("/quote/spot", json=reviewed_payload(request, customer_id=str(customer.id))).status_code == 422


def test_pricing_access_fail_closed(scenario, client, monkeypatch):
    from api.main import app
    payload = reviewed_payload(scenario[0])
    assert client.get("/admin/rates", params={"tenant_id": str(scenario[0].tenant_id)}).status_code == 403
    for headers in [{"Origin": "https://public.example"}, {"X-Forwarded-For": "127.0.0.1"}, {"Host": "public.example"}]:
        assert client.post("/quote/spot", json=payload, headers=headers).status_code == 403
    remote = TestClient(app, base_url="http://127.0.0.1", client=("192.0.2.1", 50000))
    assert remote.get("/quote/lookups").status_code == 403
    monkeypatch.delenv("CARGOAI_LOCAL_DEMO")
    assert client.post("/quote/spot", json=payload).status_code == 403
    assert client.get("/quote/lookups").status_code == 403


def test_lookup_service_failure_is_clear(client, monkeypatch):
    import api.lookups as lookups
    def unavailable():
        raise RuntimeError("Private connection information")
    monkeypatch.setattr(lookups, "get_engine", unavailable)
    for path in ["/quote/lookups", "/quote/lookups/resolve?kind=location&value=Shanghai"]:
        response = client.get(path)
        assert response.status_code == 503
        assert response.json()["detail"] == "Pricing lookup database/service unavailable"
