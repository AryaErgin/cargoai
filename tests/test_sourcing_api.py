from datetime import date
import json
import re
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import FIXED_NOW
from database.models import CarrierRFQ, RateCharge, SupplierContact
from database.repositories.customer_repository import create_customer
from sourcing import service

pytestmark = pytest.mark.usefixtures("no_network")
START_KEYS = {"quote_request_id", "sourcing_status", "rfq_drafts_created", "already_existed", "nothing_sent"}
STATUS_KEYS = {"quote_request_id", "sourcing_status", "rfq_drafts", "rfqs_sent", "replies_received",
               "rate_available", "rfqs_overdue"}


@pytest.fixture
def client(sourcing_world, sourcing_engine, monkeypatch):
    import api.main as api
    import api.sourcing as sourcing_api
    monkeypatch.setattr(sourcing_api, "get_engine", lambda: sourcing_engine)
    monkeypatch.setenv("CARGOAI_LOCAL_DEMO", "1")
    monkeypatch.setenv("CARGOAI_DEMO_TENANT_ID", str(sourcing_world.tenant_id))
    return TestClient(api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def payload(world, **changes):
    values = {key: (str(value) if not isinstance(value, (int, bool)) or value is None else value)
              for key, value in world.request(**changes).items()}
    return {key: value for key, value in values.items() if value != "None"}


def test_happy_path_returns_only_allowlisted_keys(sourcing_world, client):
    response = client.post("/sourcing/requests", json=payload(sourcing_world, commodity="Machine parts",
                                                              gross_weight_kg="18000.5", incoterm="FOB"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == START_KEYS
    assert body["sourcing_status"] == "RFQ_DRAFTED" and body["rfq_drafts_created"] == 2
    assert body["already_existed"] is False and body["nothing_sent"] is True
    again = client.post("/sourcing/requests", json=payload(sourcing_world, commodity="Machine parts",
                                                           gross_weight_kg="18000.5", incoterm="FOB")).json()
    assert again["quote_request_id"] == body["quote_request_id"] and again["already_existed"] is True
    status = client.get(f"/sourcing/requests/{body['quote_request_id']}")
    assert status.status_code == 200 and set(status.json()) == STATUS_KEYS
    assert status.json()["rfq_drafts"] == 2 and status.json()["rate_available"] is False


def test_no_supplier_data_leaks_in_any_customer_response(sourcing_world, client):
    world = sourcing_world
    responses = [client.post("/sourcing/requests", json=payload(world, customer_id=world.customer_id)),
                 client.post("/sourcing/requests", json=payload(world, customer_id=world.customer_id)),
                 client.post("/sourcing/requests", json=payload(world, origin="CNSHA", destination="TRAMR",
                                                                effective_date="2026-10-15")),
                 client.post("/sourcing/requests", json=payload(world, origin="TRAMR", destination="TRMER")),
                 client.post("/sourcing/requests", json=payload(world, dangerous_goods=True)),
                 client.get(f"/sourcing/requests/{uuid4()}")]
    request_id = responses[0].json()["quote_request_id"]
    with world.session.begin_nested():
        rfq = world.session.scalar(select(CarrierRFQ).limit(1))
    service.approve_rfq(world.session, world.tenant_id, rfq.id, now=FIXED_NOW)
    service.mark_rfq_sent(world.session, world.tenant_id, rfq.id)
    world.session.commit()
    responses.append(client.get(f"/sourcing/requests/{request_id}"))
    assert [r.status_code for r in responses] == [200, 200, 409, 200, 422, 404, 200]
    assert responses[-1].json()["rfqs_sent"] == 1
    world.session.expire_all()
    forbidden = set(world.suppliers) | {"Secret Customer Textiles AS"}
    forbidden |= set(world.session.scalars(select(SupplierContact.email)))
    forbidden |= set(world.session.scalars(select(CarrierRFQ.reference_code)))
    forbidden |= set(world.session.scalars(select(CarrierRFQ.outbound_message_id)))
    forbidden |= {str(value) for value in world.session.scalars(select(CarrierRFQ.supplier_id))}
    amounts = {format(value.normalize(), "f") for value in world.session.scalars(select(RateCharge.amount))}
    assert {"1450", "110", "45"} <= amounts
    for response in responses:
        text = json.dumps(response.json())
        assert not [value for value in forbidden if value in text], text
        assert "@" not in text and "CAI-RFQ" not in text
        assert not any(re.search(rf"(?<![\w.-]){re.escape(a)}(?![\w.-])", text) for a in amounts), text
        lowered = text.lower().replace("no_carrier_available", "")  # plan-defined status value
        assert not any(word in lowered for word in ("supplier", "carrier", "buy", "metadata", "body", "subject"))


def test_domain_errors(sourcing_world, client):
    world = sourcing_world
    rate_available = client.post("/sourcing/requests", json=payload(world, origin="CNSHA", destination="TRAMR",
                                                                    effective_date="2026-10-15"))
    assert rate_available.status_code == 409 and rate_available.json()["detail"]["status"] == "RATE_AVAILABLE"
    assert set(rate_available.json()["detail"]) == {"status", "error"}
    missing_fx = client.post("/sourcing/requests", json=payload(world, origin="CNSHA", destination="TRAMR",
                                                                effective_date="2026-10-15", requested_currency="GBP"))
    assert missing_fx.status_code == 409 and missing_fx.json()["detail"]["status"] == "RATE_AVAILABLE"
    dg = client.post("/sourcing/requests", json=payload(world, dangerous_goods=True))
    assert dg.status_code == 422 and dg.json()["detail"]["status"] == "INVALID_REQUEST"
    other = world.new_tenant("other")
    foreign = create_customer(world.session, other, name="Foreign")
    world.session.commit()
    response = client.post("/sourcing/requests", json=payload(world, customer_id=foreign.id))
    assert response.status_code == 422 and response.json()["detail"]["status"] == "INVALID_REQUEST"


def test_ambiguous_rate_conflict(sourcing_world, client):
    world = sourcing_world
    for _ in range(2):
        world.rate(world.tenant_id, world.suppliers["Example Blue Line"], "TRMER", "CNSHA",
                   valid_from=date(2026, 11, 1), valid_to=date(2026, 11, 30), created_at=FIXED_NOW)
    world.session.commit()
    response = client.post("/sourcing/requests", json=payload(world))
    assert response.status_code == 409 and response.json()["detail"]["status"] == "AMBIGUOUS_RATE"


@pytest.mark.parametrize("changes", [{"tenant_id": str(uuid4())}, {"dangerous_goods": "false"},
                                     {"dangerous_goods": None}, {"container_count": "2"}, {"container_count": 0},
                                     {"gross_weight_kg": 1.5}, {"persist": True}, {"buy_price": "10"}])
def test_strict_request_model(sourcing_world, client, changes):
    body = {**payload(sourcing_world), **changes}
    if changes.get("dangerous_goods", "x") is None:
        body.pop("dangerous_goods")
    assert client.post("/sourcing/requests", json=body).status_code == 422


def test_other_tenant_request_is_not_found(sourcing_world, client):
    world = sourcing_world
    other = world.new_tenant("other")
    world.carrier(other, "Other Carrier", capabilities=[{"origin_country_code": "TR", "destination_country_code": "CN"}])
    foreign = service.start_sourcing(world.session, other, world.request(), now=FIXED_NOW)
    world.session.commit()
    response = client.get(f"/sourcing/requests/{foreign['quote_request_id']}")
    assert response.status_code == 404 and response.json()["detail"]["status"] == "NOT_FOUND"
    assert client.get("/sourcing/requests/not-a-uuid").status_code == 422


def test_access_fails_closed(sourcing_world, client, monkeypatch):
    world = sourcing_world
    body = payload(world)
    for headers in ({"X-Forwarded-For": "203.0.113.5"}, {"Forwarded": "for=203.0.113.5"},
                    {"Origin": "https://evil.example.com"}):
        assert client.post("/sourcing/requests", json=body, headers=headers).status_code == 403
        assert client.get(f"/sourcing/requests/{uuid4()}", headers=headers).status_code == 403
    import api.main as api
    remote = TestClient(api.app, base_url="http://127.0.0.1", client=("203.0.113.5", 50000))
    assert remote.post("/sourcing/requests", json=body).status_code == 403
    public_host = TestClient(api.app, base_url="http://cargoai.example.com", client=("127.0.0.1", 50000))
    assert public_host.get(f"/sourcing/requests/{uuid4()}").status_code == 403
    other = world.new_tenant("not-demo")
    world.session.commit()
    monkeypatch.setenv("CARGOAI_DEMO_TENANT_ID", str(other))
    assert client.post("/sourcing/requests", json=body).status_code == 403
    monkeypatch.delenv("CARGOAI_LOCAL_DEMO")
    assert client.post("/sourcing/requests", json=body).status_code == 403
    assert client.get(f"/sourcing/requests/{uuid4()}").status_code == 403
    with world.session.begin_nested():
        assert world.session.scalar(select(CarrierRFQ.id).limit(1)) is None


def test_unexpected_errors_are_generic_503(sourcing_world, client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("secret database url and carrier detail")
    monkeypatch.setattr(service, "start_sourcing", broken)
    response = client.post("/sourcing/requests", json=payload(sourcing_world))
    assert response.status_code == 503 and "secret" not in response.text


def test_internal_operator_access_is_closed_by_default(monkeypatch):
    from api.access import internal_operator_access
    monkeypatch.setenv("CARGOAI_LOCAL_DEMO", "1")
    monkeypatch.setenv("CARGOAI_LOCAL_INTERNAL_OPERATOR", "1")  # phase 2 opt-in is not implemented yet
    with pytest.raises(HTTPException) as raised:
        internal_operator_access()
    assert raised.value.status_code == 403


def test_sourcing_routes_are_customer_safe_get_post_only():
    import api.main as api
    paths = {path: sorted(methods) for path, methods in api.app.openapi()["paths"].items()
             if path.startswith(("/sourcing", "/internal"))}
    assert paths == {"/sourcing/requests": ["post"], "/sourcing/requests/{quote_request_id}": ["get"]}


@pytest.mark.parametrize("weight", ["0", "0.000", "-5", "1e3", 18500.5, 18500, "abc", "12.3456", "NaN", "Infinity",
                                    "", " ", "1,000", "1234567890123456"])
def test_invalid_gross_weight_rejected(sourcing_world, client, weight):
    response = client.post("/sourcing/requests", json={**payload(sourcing_world), "gross_weight_kg": weight})
    assert response.status_code == 422
    with sourcing_world.session.begin_nested():
        assert sourcing_world.session.scalar(select(CarrierRFQ.id).limit(1)) is None


@pytest.mark.parametrize("extra", [{}, {"commodity": "   "}, {"commodity": None, "gross_weight_kg": None},
                                   {"commodity": "Machine parts", "gross_weight_kg": "18500.125"}])
def test_optional_cargo_facts_accepted(sourcing_world, client, extra):
    response = client.post("/sourcing/requests", json={**payload(sourcing_world), **extra})
    assert response.status_code == 200, response.text
    assert response.json()["rfq_drafts_created"] == 2


def test_commodity_length_limit(sourcing_world, client):
    assert client.post("/sourcing/requests", json={**payload(sourcing_world), "commodity": "x" * 256}).status_code == 422
    assert client.post("/sourcing/requests", json={**payload(sourcing_world), "commodity": "x" * 255}).status_code == 200
