"""Explicit, synthetic development data. Run after `alembic upgrade head`."""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from database.models import (Tenant, Location, LocationGroup, LocationGroupMember, EquipmentType,
                             EquipmentAlias, Supplier, ChargeType, SourceDocument)
from database.repositories.tenant_repository import create_tenant
from database.repositories.rate_repository import create_rate_sheet, create_rate, create_rate_charge
from database.repositories.pricing_rule_repository import create_pricing_rule
from database.repositories.exchange_rate_repository import create_exchange_rate
from database.models import ExchangeRate
from database.session import session_scope


EQUIPMENT = {
    "20GP": ("20-foot general purpose", "OCEAN"),
    "40GP": ("40-foot general purpose", "OCEAN"),
    "40HC": ("40-foot high cube", "OCEAN"),
    "40OT": ("40-foot open top", "OCEAN"),
    "40FR": ("40-foot flat rack", "OCEAN"),
    "REEFER": ("Refrigerated container", "OCEAN"),
    "FTL": ("Full truck load", "ROAD"),
    "LOW_BED": ("Low bed trailer", "ROAD"),
}
CHARGES = {
    "OCEAN_FREIGHT": "FREIGHT", "ORIGIN_THC": "ORIGIN", "DESTINATION_THC": "DESTINATION",
    "DOCUMENTATION": "DOCUMENTATION", "DELIVERY_ORDER": "DOCUMENTATION", "ISPS": "SECURITY",
    "ENS": "SECURITY", "BAF": "SURCHARGE", "GRI": "SURCHARGE", "INLAND_HAULAGE": "INLAND",
}


def seed_demo(session):
    existing = session.scalar(select(Tenant).where(Tenant.slug == "demo-forwarder"))
    if existing is not None:
        seed_demo_fx(session, existing.id)
        return {"tenant_id": str(existing.id), "created": False, "demo_only": True}
    tenant = create_tenant(session, name="Demo Forwarder", slug="demo-forwarder", timezone="UTC")
    equipment = {}
    for code, (display, mode) in EQUIPMENT.items():
        row = session.scalar(select(EquipmentType).where(EquipmentType.canonical_code == code))
        if row is None:
            row = EquipmentType(canonical_code=code, display_name=display, transport_mode=mode)
            session.add(row)
            session.flush()
        equipment[code] = row
    for alias in ("40HQ", "40'HC", "40 HIGH CUBE"):
        if session.scalar(select(EquipmentAlias).where(EquipmentAlias.tenant_id.is_(None), EquipmentAlias.alias == alias)) is None:
            session.add(EquipmentAlias(equipment_type_id=equipment["40HC"].id, alias=alias))
    charge_types = {}
    for code, category in CHARGES.items():
        row = session.scalar(select(ChargeType).where(ChargeType.canonical_code == code))
        if row is None:
            row = ChargeType(canonical_code=code, display_name=code.replace("_", " ").title(), category=category)
            session.add(row)
            session.flush()
        charge_types[code] = row
    locations = {}
    for name, locode, country in (("Shanghai", "CNSHA", "CN"), ("Ningbo", "CNNGB", "CN"),
                                 ("Ambarli", "TRAMR", "TR"), ("Mersin", "TRMER", "TR")):
        row = session.scalar(select(Location).where(Location.un_locode == locode))
        if row is None:
            row = Location(name=name, city=name, country_code=country, location_type="PORT", un_locode=locode)
            session.add(row)
            session.flush()
        locations[name] = row
    group = LocationGroup(tenant_id=tenant.id, name="CHINA_MAIN_PORTS", description="DEMO membership only")
    supplier = Supplier(tenant_id=tenant.id, name="Demo Ocean Carrier", supplier_type="OCEAN_CARRIER")
    session.add_all([group, supplier])
    session.flush()
    session.add_all([LocationGroupMember(tenant_id=tenant.id, location_group_id=group.id, location_id=locations[name].id)
                     for name in ("Shanghai", "Ningbo")])
    source = SourceDocument(tenant_id=tenant.id, supplier_id=supplier.id, source_type="MANUAL",
                            original_filename="DEMO synthetic seed")
    session.add(source)
    session.flush()
    sheet = create_rate_sheet(session, tenant.id, name="DEMO October 2026 ocean rates", supplier_id=supplier.id,
                              mode="OCEAN_FCL", source_type="MANUAL", status="ACTIVE", currency="USD",
                              valid_from=date(2026, 10, 1), valid_to=date(2026, 10, 31))
    rate = create_rate(session, tenant.id, rate_sheet_id=sheet.id, supplier_id=supplier.id, mode="OCEAN_FCL",
                       origin_group_id=group.id, destination_location_id=locations["Ambarli"].id,
                       equipment_type_id=equipment["40HC"].id, valid_from=date(2026, 10, 1), valid_to=date(2026, 10, 31),
                       source_document_id=source.id, source_reference="DEMO seed / rate 1", notes="SYNTHETIC DEMO VALUES ONLY")
    for code, amount, basis in (("OCEAN_FREIGHT", "1450", "PER_CONTAINER"),
                                 ("DESTINATION_THC", "110", "PER_CONTAINER"),
                                 ("DOCUMENTATION", "45", "PER_SHIPMENT")):
        create_rate_charge(session, tenant.id, rate_id=rate.id, charge_type_id=charge_types[code].id,
                           amount=Decimal(amount), currency="USD", basis=basis)
    create_pricing_rule(session, tenant.id, name="DEMO Default ocean markup 12%", mode="OCEAN_FCL",
                        rule_type="PERCENT_MARKUP", value=Decimal("12"))
    seed_demo_fx(session, tenant.id)
    return {"tenant_id": str(tenant.id), "created": True, "demo_only": True,
            "locations": 4, "equipment_types": 8, "charge_types": 10, "rates": 1, "rate_charges": 3, "exchange_rates": 2}


def seed_demo_fx(session, tenant_id):
    for base, quote, value in (("USD", "EUR", "0.90000000"), ("EUR", "USD", "1.11111111")):
        exists = session.scalar(select(ExchangeRate).where(ExchangeRate.tenant_id == tenant_id,
            ExchangeRate.base_currency == base, ExchangeRate.quote_currency == quote,
            ExchangeRate.effective_from == date(2026, 10, 1)))
        if exists is None:
            create_exchange_rate(session, tenant_id, base_currency=base, quote_currency=quote,
                rate=Decimal(value), effective_from=date(2026, 10, 1), effective_to=date(2026, 10, 31),
                source="SYNTHETIC DEMO FX ONLY - not market data")


def main():
    with session_scope() as session:
        result = seed_demo(session)
    print(result)


if __name__ == "__main__":
    main()
