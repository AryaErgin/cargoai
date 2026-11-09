from datetime import date

import pytest

from sourcing.carrier_selector import select_carriers

pytestmark = pytest.mark.usefixtures("no_network")


@pytest.fixture
def world(sourcing_world):
    sourcing_world.fresh = sourcing_world.new_tenant("selector-tenant")
    return sourcing_world


def pick(world, tenant_id=None, origin="TRMER", destination="CNSHA", equipment="40HC", **kwargs):
    return select_carriers(world.session, tenant_id or world.fresh, mode="OCEAN_FCL",
                           origin_location_id=world.locations[origin],
                           destination_location_id=world.locations[destination],
                           equipment_type_id=world.equipment[equipment], **kwargs)


def names(candidates):
    return [candidate.supplier.name for candidate in candidates]


def country(origin="TR", destination="CN", **extra):
    return {"origin_country_code": origin, "destination_country_code": destination, **extra}


def test_exact_beats_group_beats_country(world):
    group = world.group(world.fresh, "CN_PORTS", "CNSHA", "CNNGB")
    world.carrier(world.fresh, "Alpha Country", emails=("a@example.com",), capabilities=[country()])
    world.carrier(world.fresh, "Mid Group", emails=("m@example.com",),
                  capabilities=[{"origin_location_id": world.locations["TRMER"], "destination_group_id": group}])
    world.carrier(world.fresh, "Zeta Exact", emails=("z@example.com",), capabilities=[world.lane("TRMER", "CNSHA")])
    selected = pick(world)
    assert names(selected) == ["Zeta Exact", "Mid Group", "Alpha Country"]
    assert [c.metadata["specificity"] for c in selected] == [6, 5, 2]
    assert selected[1].metadata["destination_match"] == "GROUP"
    assert selected[2].metadata["origin_match"] == "COUNTRY"
    assert [c.metadata["rank"] for c in selected] == [1, 2, 3]


def test_best_capability_per_supplier_is_used(world):
    world.carrier(world.fresh, "Multi", capabilities=[country(), world.lane("TRMER", "CNSHA", priority=1)])
    [candidate] = pick(world)
    assert candidate.metadata["specificity"] == 6 and candidate.metadata["capability_priority"] == 1


def test_directional_reverse_lane_not_selected(world):
    world.carrier(world.fresh, "Eastbound Only", capabilities=[world.lane("CNSHA", "TRMER"), country("CN", "TR")])
    assert pick(world) == []
    assert names(pick(world, origin="CNSHA", destination="TRMER")) == ["Eastbound Only"]


@pytest.mark.parametrize("variant", ["inactive_supplier", "inactive_contact", "not_rfq_recipient", "no_contact",
                                     "inactive_capability", "trucker", "other_mode"])
def test_ineligible_carriers_excluded(world, variant):
    kwargs = {"capabilities": [country()]}
    if variant == "inactive_supplier":
        kwargs["is_active"] = False
    elif variant == "inactive_contact":
        kwargs["contact_active"] = False
    elif variant == "not_rfq_recipient":
        kwargs["rfq_recipient"] = False
    elif variant == "no_contact":
        kwargs["emails"] = ()
    elif variant == "inactive_capability":
        kwargs["capabilities"] = [country(is_active=False)]
    elif variant == "trucker":
        kwargs["supplier_type"] = "TRUCKER"
    world.carrier(world.fresh, "Candidate", **kwargs)
    if variant == "other_mode":
        supplier = world.carrier(world.fresh, "Air Only")
        from database.repositories.supplier_repository import create_lane_capability
        create_lane_capability(world.session, world.fresh, supplier_id=supplier.id, mode="AIR", **country())
    expected = ["Candidate"] if variant == "other_mode" else []
    assert names(pick(world)) == expected


@pytest.mark.parametrize("supplier_type", ["OCEAN_CARRIER", "NVOCC", "OVERSEAS_AGENT"])
def test_rfq_supplier_types_allowed(world, supplier_type):
    world.carrier(world.fresh, "Typed", supplier_type=supplier_type, capabilities=[country()])
    assert names(pick(world)) == ["Typed"]


def test_equipment_filter(world):
    world.carrier(world.fresh, "Only 20GP", emails=("a@example.com",),
                  capabilities=[country(equipment_type_id=world.equipment["20GP"])])
    world.carrier(world.fresh, "Only 40HC", emails=("b@example.com",),
                  capabilities=[country(equipment_type_id=world.equipment["40HC"])])
    world.carrier(world.fresh, "Any Equipment", emails=("c@example.com",), capabilities=[country()])
    assert names(pick(world)) == ["Any Equipment", "Only 40HC"]
    assert names(pick(world, equipment="20GP")) == ["Any Equipment", "Only 20GP"]


def test_lane_history_breaks_ties(world):
    world.carrier(world.fresh, "Aardvark Line", emails=("a@example.com",), capabilities=[country()])
    zulu = world.carrier(world.fresh, "Zulu Line", emails=("z@example.com",), capabilities=[country()])
    world.rate(world.fresh, zulu.id, "TRMER", "CNSHA", status="EXPIRED", valid_from=date(2025, 1, 1),
               valid_to=date(2025, 1, 31))
    selected = pick(world)
    assert names(selected) == ["Zulu Line", "Aardvark Line"]
    assert [c.metadata["has_lane_history"] for c in selected] == [True, False]


def test_priority_ranks_before_lane_history(world):
    world.carrier(world.fresh, "Preferred", emails=("p@example.com",), capabilities=[country(priority=10)])
    historic = world.carrier(world.fresh, "Historic", emails=("h@example.com",), capabilities=[country()])
    world.rate(world.fresh, historic.id, "TRMER", "CNSHA")
    assert names(pick(world)) == ["Preferred", "Historic"]


def test_history_only_carriers_invited_below_all_capability_matches(world):
    world.carrier(world.fresh, "Country Level", emails=("c@example.com",), capabilities=[country()])
    historic = world.carrier(world.fresh, "AAA History Only", emails=("h@example.com",))
    sheet_only = world.carrier(world.fresh, "AAB Sheet History", emails=("s@example.com",))
    world.rate(world.fresh, historic.id, "TRMER", "CNSHA", status="ARCHIVED")
    world.rate(world.fresh, sheet_only.id, "TRMER", "CNSHA", on_sheet=True)
    selected = pick(world)
    assert names(selected) == ["Country Level", "AAA History Only", "AAB Sheet History"]
    assert [c.metadata["selection_basis"] for c in selected] == ["CAPABILITY", "LANE_HISTORY", "LANE_HISTORY"]
    assert selected[1].metadata["capability_id"] is None


def test_history_only_requires_contact_lane_and_equipment(world):
    no_contact = world.carrier(world.fresh, "No Contact", emails=())
    reverse = world.carrier(world.fresh, "Reverse History", emails=("r@example.com",))
    other_equipment = world.carrier(world.fresh, "Other Equipment", emails=("o@example.com",))
    inactive = world.carrier(world.fresh, "Inactive History", emails=("i@example.com",), is_active=False)
    world.rate(world.fresh, no_contact.id, "TRMER", "CNSHA")
    world.rate(world.fresh, reverse.id, "CNSHA", "TRMER")
    world.rate(world.fresh, other_equipment.id, "TRMER", "CNSHA", equipment="20GP")
    world.rate(world.fresh, inactive.id, "TRMER", "CNSHA")
    assert pick(world) == []


def test_history_via_tenant_group_rate(world):
    """Seeded demo rate is CHINA_MAIN_PORTS -> Ambarli; it is history for Shanghai -> Ambarli."""
    selected = pick(world, tenant_id=world.tenant_id, origin="CNSHA", destination="TRAMR")
    demo = next(c for c in selected if c.supplier.name == "Demo Ocean Carrier")
    assert demo.metadata["has_lane_history"] is True
    assert names(selected)[0] == "Demo Ocean Carrier"


def test_total_deterministic_order(world):
    created = [world.carrier(world.fresh, name, emails=(f"{index}@example.com",), capabilities=[country()])
               for index, name in enumerate(["Same Name", "Same Name", "Beta", "alpha"])]
    first = pick(world)
    same = sorted((s for s in created if s.name == "Same Name"), key=lambda s: s.id)
    assert [c.supplier.id for c in first] == [created[2].id, same[0].id, same[1].id, created[3].id]
    for _ in range(3):
        assert [c.supplier.id for c in pick(world)] == [c.supplier.id for c in first]


def test_first_contact_by_email(world):
    world.carrier(world.fresh, "Two Contacts", emails=("zed@example.com", "amy@example.com"), capabilities=[country()])
    [candidate] = pick(world)
    assert candidate.contact.email == "amy@example.com"


def test_cap_at_max_carriers(world, monkeypatch):
    for index in range(7):
        world.carrier(world.fresh, f"Carrier {index}", emails=(f"c{index}@example.com",), capabilities=[country()])
    monkeypatch.delenv("CARGOAI_RFQ_MAX_CARRIERS", raising=False)
    selected = pick(world)
    assert len(selected) == 5 and selected[0].metadata["eligible_candidates"] == 7
    assert names(selected) == [f"Carrier {index}" for index in range(5)]
    monkeypatch.setenv("CARGOAI_RFQ_MAX_CARRIERS", "3")
    assert len(pick(world)) == 3
    assert len(pick(world, max_carriers=1)) == 1


def test_other_tenant_carriers_never_returned(world):
    world.carrier(world.tenant_id, "Demo Tenant Only", capabilities=[world.lane("TRMER", "CNSHA")])
    other_history = world.carrier(world.tenant_id, "Demo History Only", emails=("dh@example.com",))
    world.rate(world.tenant_id, other_history.id, "TRMER", "CNSHA")
    assert pick(world) == []
    own = pick(world, tenant_id=world.tenant_id)
    assert "Demo Tenant Only" in names(own) and "Demo History Only" in names(own)


def test_exclude_already_drafted_suppliers(world):
    first = world.carrier(world.fresh, "First", emails=("f@example.com",), capabilities=[country()])
    world.carrier(world.fresh, "Second", emails=("s@example.com",), capabilities=[country()])
    assert names(pick(world, exclude_supplier_ids={first.id})) == ["Second"]


def test_empty_result_and_input_validation(world):
    assert pick(world) == []
    with pytest.raises(ValueError):
        select_carriers(world.session, "not-a-tenant", mode="OCEAN_FCL", origin_location_id=world.locations["TRMER"],
                        destination_location_id=world.locations["CNSHA"], equipment_type_id=world.equipment["40HC"])
    with pytest.raises(ValueError):
        select_carriers(world.session, world.fresh, mode="OCEAN_FCL", origin_location_id="TRMER",
                        destination_location_id=world.locations["CNSHA"], equipment_type_id=world.equipment["40HC"])
