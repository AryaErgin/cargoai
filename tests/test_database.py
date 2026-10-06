from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
import subprocess
import sys
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, func, update, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.base import Base
from database.models import *
from database.repositories.tenant_repository import create_tenant, get_tenant
from database.repositories.customer_repository import create_customer, get_customer, list_customers
from database.repositories.pricing_rule_repository import create_pricing_rule, get_pricing_rule, list_pricing_rules
from database.repositories.rate_repository import (create_rate_sheet, create_rate, get_rate, list_rates,
    create_rate_charge, list_rate_charges, find_candidate_rates, create_rate_sheet_version)
from database.repositories.reference_repository import resolve_location_aliases, resolve_equipment_aliases
from database.seed import seed_demo
from database.session import build_engine


TABLES = {"tenants", "locations", "location_aliases", "location_groups", "location_group_members",
          "equipment_types", "equipment_aliases", "suppliers", "rate_sheets", "rates", "charge_types",
          "rate_charges", "customers", "pricing_rules", "source_documents", "import_profiles", "import_jobs",
          "quote_requests", "quotes", "quote_lines", "exchange_rates", "rate_events"}


def migration_config(connection):
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def engine(tmp_path):
    engine = build_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with engine.begin() as connection:
        command.upgrade(migration_config(connection), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine, expire_on_commit=False) as session:
        yield session
        session.rollback()


@pytest.fixture
def demo(session):
    result = seed_demo(session)
    session.commit()
    tenant_id = UUID(result["tenant_id"])
    rate = list_rates(session, tenant_id)[0]
    origin = session.scalar(select(Location).where(Location.name == "Shanghai"))
    destination = session.scalar(select(Location).where(Location.name == "Ambarli"))
    return tenant_id, rate, origin, destination


def candidates(session, demo, effective_date):
    tenant_id, rate, origin, destination = demo
    return find_candidate_rates(session, tenant_id, "OCEAN_FCL", origin.id, destination.id,
                                rate.equipment_type_id, effective_date)


def test_schema_migration_and_no_drift(engine):
    assert set(Base.metadata.tables) == TABLES
    assert set(inspect(engine).get_table_names()) == TABLES | {"alembic_version"}
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_model_import_registers_history_guards_in_fresh_process():
    code = """
from database.models import Rate
from sqlalchemy import event
from sqlalchemy.orm import Session
import sys
guards = sys.modules['database.session']
assert event.contains(Session, 'before_flush', guards.preserve_rate_history)
assert event.contains(Session, 'do_orm_execute', guards.reject_historical_bulk_changes)
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


def test_migration_round_trip(engine):
    with engine.begin() as connection:
        config = migration_config(connection)
        command.downgrade(config, "base")
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert set(inspect(connection).get_table_names()) == TABLES | {"alembic_version"}


def test_postgresql_offline_migration():
    output = StringIO()
    config = Config("alembic.ini", output_buffer=output)
    config.attributes["database_url"] = "postgresql+psycopg://localhost/cargoai"
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "UUID" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "NUMERIC(18, 6)" in sql
    assert sql.count("CREATE TABLE ") == 23  # Includes Alembic's version table.
    assert "BOOLEAN DEFAULT true" in sql
    assert "FOREIGN KEY(tenant_id, rate_sheet_id)" in sql


def test_tenant_creation_defaults_and_utc(session):
    tenant = create_tenant(session, name="Company A", slug="company-a")
    session.commit()
    session.expire_all()
    loaded = get_tenant(session, tenant.id)
    assert isinstance(loaded.id, UUID)
    assert loaded.default_currency == "EUR"
    assert loaded.is_active is True
    assert loaded.created_at.utcoffset() == timedelta(0)
    assert loaded.updated_at.utcoffset() == timedelta(0)


def test_duplicate_tenant_slug_rejected(session):
    create_tenant(session, name="A", slug="same")
    with pytest.raises(IntegrityError):
        create_tenant(session, name="B", slug="same")


def test_global_locations_private_aliases_and_equipment(session, demo):
    tenant_id, rate, origin, destination = demo
    other = create_tenant(session, name="B", slug="b")
    session.add_all([
        LocationAlias(location_id=origin.id, alias="SHA"),
        LocationAlias(tenant_id=tenant_id, location_id=origin.id, alias="Our port"),
        LocationAlias(tenant_id=other.id, location_id=destination.id, alias="Our port"),
        EquipmentAlias(tenant_id=other.id, equipment_type_id=rate.equipment_type_id, alias="B only"),
    ])
    session.flush()
    assert resolve_location_aliases(session, tenant_id, "SHA")[0].location_id == origin.id
    assert resolve_location_aliases(session, tenant_id, "Our port")[0].location_id == origin.id
    assert resolve_location_aliases(session, other.id, "Our port")[0].location_id == destination.id
    assert resolve_equipment_aliases(session, tenant_id, "40HQ")[0].equipment_type_id == rate.equipment_type_id
    assert resolve_equipment_aliases(session, tenant_id, "B only") == []
    assert "tenant_id" not in Location.__table__.columns


def test_private_alias_precedes_global_alias(session, demo):
    tenant_id, rate, origin, destination = demo
    session.add_all([LocationAlias(alias="custom", location_id=origin.id),
                     LocationAlias(alias="custom", tenant_id=tenant_id, location_id=destination.id)])
    session.flush()
    assert [r.location_id for r in resolve_location_aliases(session, tenant_id, "custom")] == [destination.id]


def test_group_membership_unique(session, demo):
    tenant_id, rate, origin, _ = demo
    session.add(LocationGroupMember(tenant_id=tenant_id, location_group_id=rate.origin_group_id, location_id=origin.id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_group_membership_cross_tenant_rejected(session, demo):
    tenant_id, rate, origin, destination = demo
    other = create_tenant(session, name="B", slug="b")
    session.add(LocationGroupMember(tenant_id=other.id, location_group_id=rate.origin_group_id, location_id=destination.id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_supplier_and_multiple_rate_charges(session, demo):
    tenant_id, rate, _, _ = demo
    supplier = session.scalar(select(Supplier).where(Supplier.tenant_id == tenant_id))
    assert supplier.name == "Demo Ocean Carrier"
    charges = list_rate_charges(session, tenant_id, rate.id)
    assert len(charges) == 3
    assert sorted(charge.amount for charge in charges) == [Decimal("45"), Decimal("110"), Decimal("1450")]


@pytest.mark.parametrize("effective_date, expected", [
    (date(2026, 9, 30), 0), (date(2026, 10, 1), 1), (date(2026, 10, 31), 1), (date(2026, 11, 1), 0),
])
def test_effective_date_inclusive_filtering(session, demo, effective_date, expected):
    assert len(candidates(session, demo, effective_date)) == expected


def test_candidate_equipment_and_destination_group(session, demo):
    tenant_id, rate, origin, destination = demo
    group = LocationGroup(tenant_id=tenant_id, name="Destination zone")
    session.add(group)
    session.flush()
    session.add(LocationGroupMember(tenant_id=tenant_id, location_group_id=group.id, location_id=destination.id))
    new_rate = create_rate(session, tenant_id, rate_sheet_id=rate.rate_sheet_id, mode="OCEAN_FCL",
                           origin_location_id=origin.id, destination_group_id=group.id)
    assert new_rate.id in {r.id for r in candidates(session, demo, date(2026, 10, 5))}
    mismatched = find_candidate_rates(session, tenant_id, "OCEAN_FCL", origin.id, destination.id, uuid4(), date(2026, 10, 5))
    assert [r.id for r in mismatched] == [new_rate.id]


def test_unbounded_and_draft_validity(session, demo):
    tenant_id, _, origin, destination = demo
    sheet = create_rate_sheet(session, tenant_id, name="Draft", mode="OCEAN_FCL", source_type="MANUAL")
    create_rate(session, tenant_id, rate_sheet_id=sheet.id, mode="OCEAN_FCL", origin_location_id=origin.id,
                destination_location_id=destination.id)
    assert candidates(session, demo, date(2030, 1, 1)) == []
    active = create_rate_sheet(session, tenant_id, name="Open ended", mode="OCEAN_FCL", source_type="MANUAL", status="ACTIVE")
    row = create_rate(session, tenant_id, rate_sheet_id=active.id, mode="OCEAN_FCL", origin_location_id=origin.id,
                      destination_location_id=destination.id)
    assert [r.id for r in candidates(session, demo, date(2030, 1, 1))] == [row.id]


def test_history_clone_and_immutable_rows(session, demo):
    tenant_id, original, _, _ = demo
    old_charge = next(c for c in list_rate_charges(session, tenant_id, original.id) if c.amount == Decimal("1450"))
    new_sheet = create_rate_sheet_version(session, tenant_id, original.rate_sheet_id,
                                          charge_changes={old_charge.id: {"amount": Decimal("1500")}})
    session.commit()
    assert new_sheet.version == 2
    assert new_sheet.parent_rate_sheet_id == original.rate_sheet_id
    new_rate = list_rates(session, tenant_id, rate_sheet_id=new_sheet.id)[0]
    assert new_rate.id != original.id
    assert old_charge.amount == Decimal("1450")
    assert Decimal("1500") in [c.amount for c in list_rate_charges(session, tenant_id, new_rate.id)]
    assert len(list_rates(session, tenant_id)) == 2
    original.notes = "overwrite"
    with pytest.raises(ValueError, match="append-only"):
        session.flush()


def test_duplicate_successor_version_rejected(session, demo):
    tenant_id, rate, _, _ = demo
    create_rate_sheet_version(session, tenant_id, rate.rate_sheet_id)
    with pytest.raises(IntegrityError):
        create_rate_sheet_version(session, tenant_id, rate.rate_sheet_id)


def test_historical_deletion_rejected(session, demo):
    _, rate, _, _ = demo
    session.delete(rate)
    with pytest.raises(ValueError, match="append-only"):
        session.flush()


@pytest.mark.parametrize("operation", [update(Rate).values(notes="changed"), delete(Rate)])
def test_bulk_history_change_rejected(session, demo, operation):
    with pytest.raises(ValueError, match="append-only"):
        session.execute(operation)


def test_tenant_ownership_cannot_be_reassigned(session, demo):
    tenant_id, _, _, _ = demo
    customer = create_customer(session, tenant_id, name="A Customer")
    other = create_tenant(session, name="B", slug="b")
    session.commit()
    customer.tenant_id = other.id
    with pytest.raises(ValueError, match="ownership cannot be changed"):
        session.flush()


def test_tenant_isolation_and_independent_same_lane_prices(session, demo):
    tenant_a, rate_a, origin, destination = demo
    tenant_b = create_tenant(session, name="Company B", slug="company-b")
    customer_b = create_customer(session, tenant_b.id, name="B Customer")
    rule_b = create_pricing_rule(session, tenant_b.id, name="B markup", rule_type="PERCENT_MARKUP", value=Decimal("8"))
    sheet_b = create_rate_sheet(session, tenant_b.id, name="B rates", mode="OCEAN_FCL", source_type="MANUAL", status="ACTIVE")
    rate_b = create_rate(session, tenant_b.id, rate_sheet_id=sheet_b.id, mode="OCEAN_FCL", origin_location_id=origin.id,
                         destination_location_id=destination.id, equipment_type_id=rate_a.equipment_type_id)
    charge_type = session.scalar(select(ChargeType).where(ChargeType.canonical_code == "OCEAN_FREIGHT"))
    create_rate_charge(session, tenant_b.id, rate_id=rate_b.id, charge_type_id=charge_type.id,
                       amount=Decimal("1700"), currency="USD", basis="PER_CONTAINER")
    assert get_rate(session, tenant_a, rate_b.id) is None
    assert get_rate(session, tenant_b.id, rate_a.id) is None
    assert get_customer(session, tenant_a, customer_b.id) is None
    assert get_pricing_rule(session, tenant_a, rule_b.id) is None
    assert list_customers(session, tenant_a) == []
    assert rule_b.id not in {r.id for r in list_pricing_rules(session, tenant_a)}
    assert [r.id for r in list_rates(session, tenant_b.id)] == [rate_b.id]
    assert list_rate_charges(session, tenant_a, rate_b.id) == []
    matches_b = find_candidate_rates(session, tenant_b.id, "OCEAN_FCL", origin.id, destination.id, rate_a.equipment_type_id, date(2026, 10, 5))
    assert [r.id for r in matches_b] == [rate_b.id]
    assert list_rate_charges(session, tenant_b.id, rate_b.id)[0].amount == Decimal("1700")
    assert Decimal("1450") in [c.amount for c in list_rate_charges(session, tenant_a, rate_a.id)]


@pytest.mark.parametrize("target", ["sheet", "supplier", "group", "source"])
def test_cross_tenant_rate_references_rejected(session, demo, target):
    tenant_a, rate, origin, destination = demo
    other = create_tenant(session, name="B", slug="b")
    sheet = create_rate_sheet(session, other.id, name="B", mode="OCEAN_FCL", source_type="MANUAL")
    fields = dict(rate_sheet_id=sheet.id, mode="OCEAN_FCL", origin_location_id=origin.id, destination_location_id=destination.id)
    if target == "sheet":
        fields["rate_sheet_id"] = rate.rate_sheet_id
    elif target == "supplier":
        fields["supplier_id"] = rate.supplier_id
    elif target == "group":
        fields.update(origin_location_id=None, origin_group_id=rate.origin_group_id)
    else:
        fields["source_document_id"] = rate.source_document_id
    with pytest.raises(IntegrityError):
        create_rate(session, other.id, **fields)


def test_cross_tenant_customer_rule_reference_rejected(session, demo):
    tenant_id, _, _, _ = demo
    other = create_tenant(session, name="B", slug="b")
    customer = create_customer(session, other.id, name="B")
    with pytest.raises(IntegrityError):
        create_pricing_rule(session, tenant_id, name="Injected", customer_id=customer.id,
                            rule_type="FIXED_MARKUP", value=Decimal("10"))


@pytest.mark.parametrize("fields", [
    {"valid_from": date(2026, 11, 1), "valid_to": date(2026, 10, 1)},
    {"transit_days_min": 5, "transit_days_max": 2},
    {"origin_group_id": "demo"},
])
def test_invalid_rate_validation(session, demo, fields):
    tenant_id, rate, origin, destination = demo
    if fields.get("origin_group_id") == "demo":
        fields = {"origin_group_id": rate.origin_group_id}
    with pytest.raises(IntegrityError):
        create_rate(session, tenant_id, rate_sheet_id=rate.rate_sheet_id, mode="OCEAN_FCL",
                    origin_location_id=origin.id, destination_location_id=destination.id, **fields)


def test_explicit_tenant_required(session):
    for tenant_id in (None, "", "not-a-uuid"):
        with pytest.raises(ValueError, match="tenant UUID"):
            list_rates(session, tenant_id)
        with pytest.raises(ValueError, match="tenant UUID"):
            list_customers(session, tenant_id)
        with pytest.raises(ValueError, match="tenant UUID"):
            list_pricing_rules(session, tenant_id)


def test_import_profile_job_and_source_traceability(session, demo):
    tenant_id, rate, _, _ = demo
    document = session.get(SourceDocument, rate.source_document_id)
    assert document.source_type == "MANUAL"
    assert rate.source_reference == "DEMO seed / rate 1"
    profile = ImportProfile(tenant_id=tenant_id, supplier_id=rate.supplier_id, name="Reusable carrier mapping",
                            source_type="EXCEL", configuration_json={"POL": "origin", "POD": "destination", "OF": "OCEAN_FREIGHT"})
    session.add(profile)
    session.flush()
    job = ImportJob(tenant_id=tenant_id, source_document_id=document.id, import_profile_id=profile.id,
                    rows_received=10, rows_imported=9, rows_rejected=1, status="REVIEW_REQUIRED")
    session.add(job)
    session.commit()
    session.expire_all()
    assert session.get(ImportProfile, profile.id).configuration_json["OF"] == "OCEAN_FREIGHT"
    assert session.get(ImportJob, job.id).rows_received == 10
    assert "file_bytes" not in SourceDocument.__table__.columns


def test_quotes_preserve_charge_version_and_line_snapshot(session, demo):
    tenant_id, rate, _, _ = demo
    charge = list_rate_charges(session, tenant_id, rate.id)[0]
    request = QuoteRequest(tenant_id=tenant_id, mode="OCEAN_FCL")
    session.add(request)
    session.flush()
    quote = Quote(tenant_id=tenant_id, quote_request_id=request.id, currency="USD")
    session.add(quote)
    session.flush()
    line = QuoteLine(tenant_id=tenant_id, quote_id=quote.id, rate_id=rate.id, rate_charge_id=charge.id,
                     description="Stored quote snapshot", quantity=Decimal("2"), unit_amount=charge.amount,
                     total_amount=Decimal("2900"), currency="USD", basis=charge.basis)
    session.add(line)
    session.commit()
    successor = create_rate_sheet_version(session, tenant_id, rate.rate_sheet_id)
    session.commit()
    session.expire_all()
    loaded = session.get(QuoteLine, line.id)
    assert loaded.rate_id == rate.id
    assert loaded.rate_charge_id == charge.id
    assert loaded.total_amount == Decimal("2900")
    assert loaded.quote_id == quote.id
    assert session.get(QuoteRequest, request.id).source_text is None
    assert successor.version == 2


def test_cross_tenant_quote_line_rejected(session, demo):
    tenant_a, rate, _, _ = demo
    other = create_tenant(session, name="B", slug="b")
    quote = Quote(tenant_id=other.id, currency="USD")
    session.add(quote)
    session.flush()
    session.add(QuoteLine(tenant_id=other.id, quote_id=quote.id, rate_id=rate.id,
                          description="Injected", quantity=1, unit_amount=1, total_amount=1, currency="USD", basis="FLAT"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_quote_line_charge_must_belong_to_its_rate(session, demo):
    tenant_id, rate, _, _ = demo
    successor = create_rate_sheet_version(session, tenant_id, rate.rate_sheet_id)
    wrong_rate = list_rates(session, tenant_id, rate_sheet_id=successor.id)[0]
    charge = list_rate_charges(session, tenant_id, rate.id)[0]
    quote = Quote(tenant_id=tenant_id, currency="USD")
    session.add(quote)
    session.flush()
    session.add(QuoteLine(tenant_id=tenant_id, quote_id=quote.id, rate_id=wrong_rate.id, rate_charge_id=charge.id,
                          description="Wrong provenance", quantity=1, unit_amount=1, total_amount=1,
                          currency="USD", basis="FLAT"))
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("reference", ["document", "profile"])
def test_cross_tenant_import_references_rejected(session, demo, reference):
    tenant_id, rate, _, _ = demo
    other = create_tenant(session, name="B", slug="b")
    fields = {}
    if reference == "document":
        fields["source_document_id"] = rate.source_document_id
    else:
        profile = ImportProfile(tenant_id=tenant_id, name="A profile", source_type="EXCEL", configuration_json={})
        session.add(profile)
        session.flush()
        fields["import_profile_id"] = profile.id
    session.add(ImportJob(tenant_id=other.id, **fields))
    with pytest.raises(IntegrityError):
        session.flush()


def test_seed_idempotence(session, demo):
    assert seed_demo(session)["created"] is False
    assert session.scalar(select(func.count()).select_from(Tenant)) == 1
    assert session.scalar(select(func.count()).select_from(Rate)) == 1
    assert session.scalar(select(func.count()).select_from(EquipmentType)) == 8
    assert session.scalar(select(func.count()).select_from(ChargeType)) == 10


def test_database_health_success_and_failure(engine, monkeypatch):
    from fastapi.testclient import TestClient
    import api.main as api
    client = TestClient(api.app)
    monkeypatch.setattr(api, "get_engine", lambda: engine)
    assert client.get("/health/db").json() == {"status": "ok", "database": "connected"}
    def broken():
        raise RuntimeError("secret postgres URL")
    monkeypatch.setattr(api, "get_engine", broken)
    response = client.get("/health/db")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert client.get("/health").json() == {"status": "ok"}


def test_existing_parse_endpoints_do_not_persist(engine, monkeypatch):
    from fastapi.testclient import TestClient
    import api.main as api
    monkeypatch.setattr(api, "get_engine", lambda: engine)
    monkeypatch.setattr(api, "parse_spot_rfq", lambda text: {"origin": "Shanghai"})
    monkeypatch.setattr(api, "parse_freight_tender", lambda text: {"equipment_type": "40HC"})
    client = TestClient(api.app)
    assert client.post("/parse/spot", json={"text": "example"}).json() == {"type": "spot_rfq", "result": {"origin": "Shanghai"}}
    assert client.post("/parse/tender", json={"text": "example"}).json() == {"type": "freight_tender", "result": {"equipment_type": "40HC"}}
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(QuoteRequest)) == 0
