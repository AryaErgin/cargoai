"""Deterministic carrier selection for a directional ocean-FCL lane (no LLM).

Eligible: active tenant supplier of an RFQ type, with an active RFQ contact, not already drafted, and
either (a) an active capability matching origin AND destination (directional) and equipment, or
(b) lane history: any Rate (any status, incl. expired) for this directional lane and equipment (Q4).

Ranking (descending): capability-matched before history-only, capability specificity
(location=3, group=2, country=1, summed per side), capability priority, has_lane_history,
then Supplier.name ascending, then Supplier.id ascending - a total order with no ties.
"""
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import or_, select

from database.models import Location, Rate, RateSheet, Supplier, SupplierContact
from database.repositories._scoped import require_tenant
from database.repositories.supplier_repository import list_lane_capabilities, list_rfq_contacts, list_rfq_suppliers
from pricing.matching import location_groups
from sourcing import config

SELECTOR_VERSION = "carrier_selector_v1"
RANKING_ORDER = ["selection_basis", "specificity", "capability_priority", "has_lane_history", "supplier_name",
                 "supplier_id"]
MATCH_SCORES = {"LOCATION": 3, "GROUP": 2, "COUNTRY": 1}


@dataclass(frozen=True)
class CarrierCandidate:
    supplier: Supplier
    contact: SupplierContact
    metadata: dict = field(default_factory=dict)


def _side_match(capability, side, location, groups):
    if getattr(capability, f"{side}_location_id") is not None:
        return "LOCATION" if getattr(capability, f"{side}_location_id") == location.id else None
    if getattr(capability, f"{side}_group_id") is not None:
        return "GROUP" if getattr(capability, f"{side}_group_id") in groups else None
    country = getattr(capability, f"{side}_country_code")
    if country is not None and location.country_code:
        return "COUNTRY" if country.upper() == location.country_code.upper() else None
    return None


def _best_capability(capabilities, origin, destination, origin_groups, destination_groups, equipment_type_id):
    best = None
    for capability in capabilities:
        if capability.equipment_type_id is not None and capability.equipment_type_id != equipment_type_id:
            continue
        origin_match = _side_match(capability, "origin", origin, origin_groups)
        destination_match = _side_match(capability, "destination", destination, destination_groups)
        if origin_match is None or destination_match is None:
            continue
        specificity = MATCH_SCORES[origin_match] + MATCH_SCORES[destination_match]
        key = (specificity, capability.priority)
        # Equal keys: lowest capability id wins so audit metadata is reproducible.
        if best is None or key > best[0] or (key == best[0] and capability.id < best[1].id):
            best = (key, capability, origin_match, destination_match)
    return best


def _lane_history_suppliers(session, tenant_id, mode, origin, destination, origin_groups, destination_groups,
                            equipment_type_id):
    """Suppliers with any rate (any status/validity) covering this directional lane and equipment."""
    rows = session.execute(select(Rate.supplier_id, RateSheet.supplier_id).join(
        RateSheet, (RateSheet.id == Rate.rate_sheet_id) & (RateSheet.tenant_id == Rate.tenant_id)).where(
        Rate.tenant_id == tenant_id, Rate.mode == mode, Rate.equipment_type_id == equipment_type_id,
        or_(Rate.origin_location_id == origin.id, Rate.origin_group_id.in_(list(origin_groups))),
        or_(Rate.destination_location_id == destination.id,
            Rate.destination_group_id.in_(list(destination_groups)))))
    return {rate_supplier if rate_supplier is not None else sheet_supplier
            for rate_supplier, sheet_supplier in rows} - {None}


def select_carriers(session, tenant_id, *, mode, origin_location_id, destination_location_id, equipment_type_id,
                    exclude_supplier_ids=(), max_carriers=None) -> list[CarrierCandidate]:
    require_tenant(tenant_id)
    for value in (origin_location_id, destination_location_id, equipment_type_id):
        if not isinstance(value, UUID):
            raise ValueError("Origin, destination and equipment must be explicit UUIDs")
    limit = config.max_carriers() if max_carriers is None else max_carriers
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("max_carriers must be a positive integer")
    origin = session.get(Location, origin_location_id)
    destination = session.get(Location, destination_location_id)
    if origin is None or destination is None:
        return []
    origin_groups = location_groups(session, tenant_id, origin.id)
    destination_groups = location_groups(session, tenant_id, destination.id)

    excluded = set(exclude_supplier_ids)
    suppliers = {row.id: row for row in list_rfq_suppliers(session, tenant_id) if row.id not in excluded}
    contacts = {}
    for contact in list_rfq_contacts(session, tenant_id, suppliers.keys()):
        contacts.setdefault(contact.supplier_id, contact)  # first by email, then id
    capabilities = {}
    for capability in list_lane_capabilities(session, tenant_id, mode=mode, active_only=True):
        capabilities.setdefault(capability.supplier_id, []).append(capability)
    history = _lane_history_suppliers(session, tenant_id, mode, origin, destination, origin_groups,
                                      destination_groups, equipment_type_id)

    ranked = []
    for supplier_id, supplier in suppliers.items():
        contact = contacts.get(supplier_id)
        if contact is None:
            continue
        best = _best_capability(capabilities.get(supplier_id, []), origin, destination, origin_groups,
                                destination_groups, equipment_type_id)
        has_history = supplier_id in history
        if best is None and not has_history:
            continue
        if best is not None:
            (specificity, priority), capability, origin_match, destination_match = best
            metadata = {"selection_basis": "CAPABILITY", "capability_id": str(capability.id),
                        "origin_match": origin_match, "destination_match": destination_match,
                        "specificity": specificity, "capability_priority": priority}
            tier = 1
        else:
            specificity = priority = 0
            metadata = {"selection_basis": "LANE_HISTORY", "capability_id": None, "origin_match": None,
                        "destination_match": None, "specificity": 0, "capability_priority": 0}
            tier = 0
        metadata.update(has_lane_history=has_history, contact_id=str(contact.id))
        key = (-tier, -specificity, -priority, -int(has_history), supplier.name, supplier.id)
        ranked.append((key, supplier, contact, metadata))
    ranked.sort(key=lambda item: item[0])
    selected = []
    for rank, (_, supplier, contact, metadata) in enumerate(ranked[:limit], start=1):
        selected.append(CarrierCandidate(supplier, contact, {
            "selector_version": SELECTOR_VERSION, "rank": rank, "eligible_candidates": len(ranked),
            "max_carriers": limit, "ranking_order": RANKING_ORDER, **metadata}))
    return selected
