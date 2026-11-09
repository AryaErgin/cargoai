"""Shared carrier-sourcing fixtures. Names are prefixed so existing per-module fixtures are unaffected."""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
import socket
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import ChargeType, EquipmentType, Location, LocationGroup, LocationGroupMember, Supplier
from database.repositories.customer_repository import create_customer
from database.repositories.rate_repository import create_rate, create_rate_charge, create_rate_sheet
from database.repositories.supplier_repository import (create_lane_capability, create_supplier,
                                                       create_supplier_contact)
from database.repositories.tenant_repository import create_tenant
from database.seed import seed_demo
from database.session import build_engine

FIXED_NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def no_network(monkeypatch):
    """Any outbound connection or SMTP use fails the test: sourcing must never send anything.

    Loopback stays allowed because the asyncio event loop (TestClient) uses a local socketpair on Windows.
    """
    original_connect = socket.socket.connect

    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in sourcing tests")

    def loopback_only(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in {"127.0.0.1", "::1", "localhost"}:
            blocked()
        return original_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    monkeypatch.setattr(socket, "create_connection", blocked)
    import smtplib
    monkeypatch.setattr(smtplib, "SMTP", blocked)
    monkeypatch.setattr(smtplib, "SMTP_SSL", blocked)


@pytest.fixture
def sourcing_engine(tmp_path):
    engine = build_engine(f"sqlite:///{(tmp_path / 'sourcing.db').as_posix()}")
    config = Config("alembic.ini")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def sourcing_session(sourcing_engine):
    with Session(sourcing_engine, expire_on_commit=False) as session:
        yield session
        session.rollback()


@dataclass
class SourcingWorld:
    session: Session
    tenant_id: UUID
    locations: dict
    equipment: dict
    china_group_id: UUID
    customer_id: UUID
    suppliers: dict = field(default_factory=dict)

    def request(self, origin="TRMER", destination="CNSHA", equipment="40HC", **changes):
        values = {"origin_location_id": self.locations[origin], "destination_location_id": self.locations[destination],
                  "equipment_type_id": self.equipment[equipment], "container_count": 2,
                  "effective_date": date(2026, 11, 20), "requested_currency": "USD", "dangerous_goods": False}
        values.update(changes)
        return values

    def new_tenant(self, slug):
        return create_tenant(self.session, name=f"Tenant {slug}", slug=slug).id

    def carrier(self, tenant_id, name, *, supplier_type="OCEAN_CARRIER", emails=("rates@example.com",),
                capabilities=(), is_active=True, rfq_recipient=True, contact_active=True):
        supplier = create_supplier(self.session, tenant_id, name=name, supplier_type=supplier_type, is_active=is_active)
        for email in emails:
            create_supplier_contact(self.session, tenant_id, supplier_id=supplier.id, email=email,
                                    is_rfq_recipient=rfq_recipient, is_active=contact_active)
        for spec in capabilities:
            create_lane_capability(self.session, tenant_id, supplier_id=supplier.id, mode="OCEAN_FCL", **spec)
        return supplier

    def lane(self, origin, destination, **extra):
        return {"origin_location_id": self.locations[origin], "destination_location_id": self.locations[destination],
                **extra}

    def group(self, tenant_id, name, *locodes):
        group = LocationGroup(tenant_id=tenant_id, name=name)
        self.session.add(group)
        self.session.flush()
        self.session.add_all([LocationGroupMember(tenant_id=tenant_id, location_group_id=group.id,
                                                  location_id=self.locations[code]) for code in locodes])
        self.session.flush()
        return group.id

    def rate(self, tenant_id, supplier_id, origin, destination, equipment="40HC", *, status="ACTIVE",
             valid_from=date(2026, 10, 1), valid_to=date(2026, 10, 31), amount="999.25", on_sheet=False, **extra):
        sheet = create_rate_sheet(self.session, tenant_id, name="Test sheet", mode="OCEAN_FCL", source_type="MANUAL",
                                  status="ACTIVE", supplier_id=supplier_id if on_sheet else None,
                                  valid_from=valid_from, valid_to=valid_to)
        rate = create_rate(self.session, tenant_id, rate_sheet_id=sheet.id, mode="OCEAN_FCL",
                           supplier_id=None if on_sheet else supplier_id, status=status,
                           origin_location_id=self.locations[origin], destination_location_id=self.locations[destination],
                           equipment_type_id=self.equipment[equipment], valid_from=valid_from, valid_to=valid_to, **extra)
        charge = self.session.scalar(select(ChargeType).where(ChargeType.canonical_code == "OCEAN_FREIGHT"))
        create_rate_charge(self.session, tenant_id, rate_id=rate.id, charge_type_id=charge.id,
                           amount=Decimal(amount), currency="USD", basis="PER_CONTAINER")
        return rate


@pytest.fixture
def sourcing_world(sourcing_session):
    session = sourcing_session
    seed = seed_demo(session)
    tenant_id = UUID(seed["tenant_id"])
    customer = create_customer(session, tenant_id, name="Secret Customer Textiles AS")
    session.commit()
    world = SourcingWorld(
        session=session, tenant_id=tenant_id,
        locations={row.un_locode: row.id for row in session.scalars(select(Location))},
        equipment={row.canonical_code: row.id for row in session.scalars(select(EquipmentType))},
        china_group_id=session.scalar(select(LocationGroup.id).where(LocationGroup.tenant_id == tenant_id)),
        customer_id=customer.id,
        suppliers={row.name: row.id for row in session.scalars(select(Supplier).where(Supplier.tenant_id == tenant_id))})
    return world
