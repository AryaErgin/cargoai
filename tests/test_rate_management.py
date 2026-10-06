from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, func

from tests.test_commercial_rates import session, scenario
from database.models import Rate, RateCharge, RateSheet, ChargeType, Quote, QuoteLine, LocationGroup, Supplier, RateEvent
from database.repositories.tenant_repository import create_tenant
from pricing.pricing_engine import price_quote
from rate_management import service
from rate_management.models import SheetCreate, RateCreate, ChargeCreate, RateVersion, RatePatch
from rate_management.exceptions import RateManagementError


def test_october_november_version_and_history(session, scenario):
    request, original = scenario
    october = price_quote(session, request, persist=True)
    freight = session.scalar(select(RateCharge).join(ChargeType).where(
        RateCharge.rate_id == original.id, ChargeType.canonical_code == 'OCEAN_FREIGHT'))
    result = service.create_rate_version(session, request.tenant_id, original.id, RateVersion(
        tenant_id=request.tenant_id, changes={'valid_from': '2026-11-01', 'valid_to': '2026-11-30'},
        charge_changes={str(freight.id): {'amount': '1380'}}))
    november = price_quote(session, request.model_copy(update={'effective_date': date(2026, 11, 15)}))
    assert october.buy_total == Decimal('3165.00')
    assert october.sell_total == Decimal('3544.80')
    assert november.buy_total == Decimal('3025.00')
    assert november.sell_total == Decimal('3388.00')
    assert november.selected_rate_id == UUID(result['new_rate_id'])
    assert price_quote(session, request).selected_rate_id == original.id
    assert session.get(Quote, october.quote_id).buy_total == Decimal('3165.00')
    assert all(line.rate_id == original.id for line in session.scalars(select(QuoteLine).where(QuoteLine.quote_id == october.quote_id)))
    assert freight.amount == Decimal('1450')
    assert any(change['field'] == 'valid_to' for change in result['changes'])
    assert any('OCEAN_FREIGHT' in change['field'] for change in result['changes'])


def new_sheet(session, request, original, **changes):
    return service.create_rate_sheet(session, request.tenant_id, SheetCreate(
        tenant_id=request.tenant_id, supplier_id=original.supplier_id, name='Manual test', currency='usd', **changes))


def rate_input(request, original, sheet_id, **changes):
    values = dict(tenant_id=request.tenant_id, rate_sheet_id=sheet_id,
        supplier_id=original.supplier_id, equipment_type_id=original.equipment_type_id,
        origin_location_id=request.origin_location_id, destination_location_id=request.destination_location_id,
        valid_from=date(2026, 11, 1), valid_to=date(2026, 11, 30))
    values.update(changes)
    return RateCreate(**values)


def charge(amount='1700', **changes):
    return ChargeCreate(**dict(charge_type='OCEAN_FREIGHT', amount=amount, currency='usd', basis='PER_CONTAINER', **changes))


def test_draft_assembly_activation_and_archive(session, scenario):
    request, original = scenario
    sheet = new_sheet(session, request, original)
    made = service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id']))
    rate_id = UUID(made['rate']['id'])
    november = request.model_copy(update={'effective_date': date(2026, 11, 15)})
    assert price_quote(session, november).status == 'NO_RATE_FOUND'
    service.add_rate_charge(session, request.tenant_id, rate_id, charge())
    result = service.update_rate(session, request.tenant_id, rate_id, RatePatch(tenant_id=request.tenant_id, changes={'status': 'ACTIVE'}))
    assert result['rate']['status'] == 'ACTIVE'
    assert price_quote(session, november).buy_total == Decimal('3400')
    service.deactivate_rate(session, request.tenant_id, rate_id, status='EXPIRED')
    assert price_quote(session, november).status == 'NO_RATE_FOUND'
    service.deactivate_rate(session, request.tenant_id, rate_id)
    assert session.get(Rate, rate_id) is not None
    assert service.get_rate_details(session, request.tenant_id, rate_id)['status'] == 'ARCHIVED'
    with pytest.raises(RateManagementError):
        service.update_rate(session, request.tenant_id, rate_id, RatePatch(tenant_id=request.tenant_id, changes={'status': 'ACTIVE'}))


def test_active_charge_addition_versions_and_metadata_edit_is_audited(session, scenario):
    request, original = scenario
    service.update_rate(session, request.tenant_id, original.id, RatePatch(tenant_id=request.tenant_id, changes={'notes': 'descriptive'}))
    assert original.notes == 'descriptive'
    result = service.add_rate_charge(session, request.tenant_id, original.id,
        ChargeCreate(charge_type='ISPS', amount='7', currency='USD', basis='FLAT'))
    assert result['new_rate_id'] != str(original.id)
    assert len(service.get_rate_details(session, request.tenant_id, original.id)['charges']) == 3
    assert len(result['rate']['charges']) == 4
    assert result['rate']['previous_version_ids'] == [str(original.id)]
    assert service.get_rate_details(session, request.tenant_id, original.id)['newer_version_ids'] == [result['new_rate_id']]
    assert session.scalar(select(func.count()).select_from(RateEvent).where(RateEvent.tenant_id == request.tenant_id)) >= 2
    with pytest.raises(RateManagementError):
        service.create_rate_version(session, request.tenant_id, original.id, RateVersion(tenant_id=request.tenant_id, changes={'priority': 2}))


def test_cross_tenant_reads_and_writes_rejected(session, scenario):
    request, original = scenario
    other = create_tenant(session, name='Other', slug='other')
    for function, args in ((service.get_rate_details, (original.id,)),
                           (service.deactivate_rate, (original.id,))):
        with pytest.raises(RateManagementError) as error:
            function(session, other.id, *args)
        assert error.value.http_status == 404
    assert service.list_rates(session, other.id)['items'] == []
    with pytest.raises(RateManagementError):
        service.create_rate_sheet(session, other.id, SheetCreate(tenant_id=other.id, supplier_id=original.supplier_id, name='bad'))
    group = LocationGroup(tenant_id=other.id, name='foreign group')
    session.add(group)
    session.flush()
    sheet = new_sheet(session, request, original)
    with pytest.raises(RateManagementError):
        service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id'], origin_location_id=None, origin_group_id=group.id))
    with pytest.raises(RateManagementError):
        service.create_rate_version(session, other.id, original.id, RateVersion(tenant_id=other.id, changes={'priority': 5}))


@pytest.mark.parametrize('changes', [
    {'origin_group_id': uuid4()}, {'destination_location_id': None},
    {'valid_from': date(2026, 12, 1), 'valid_to': date(2026, 11, 1)},
    {'equipment_type_id': uuid4()}, {'commercial_type': 'CONTRACT'}, {'supplier_id': uuid4()}])
def test_invalid_rates_are_atomic(session, scenario, changes):
    request, original = scenario
    sheet = new_sheet(session, request, original)
    before = session.scalar(select(func.count()).select_from(Rate))
    with pytest.raises(RateManagementError):
        service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id'], **changes))
    assert session.scalar(select(func.count()).select_from(Rate)) == before


def test_charge_validation_and_duplicate_charge(session, scenario):
    request, original = scenario
    sheet = new_sheet(session, request, original)
    made = service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id']))
    rate_id = UUID(made['rate']['id'])
    for item in (charge('5', percentage_base='FREIGHT_SUBTOTAL'),
        ChargeCreate(charge_type='ISPS', amount='105', currency='USD', basis='PERCENTAGE', percentage_base='BUY_SUBTOTAL'),
        ChargeCreate(charge_type='ISPS', amount='5', currency='USD', basis='PERCENTAGE'),
        charge('5', valid_to=date(2026, 10, 31)), charge('5', minimum_amount='8', maximum_amount='4')):
        with pytest.raises(RateManagementError):
            service.add_rate_charge(session, request.tenant_id, rate_id, item)
    service.add_rate_charge(session, request.tenant_id, rate_id, charge('100'))
    with pytest.raises(RateManagementError) as error:
        service.add_rate_charge(session, request.tenant_id, rate_id, charge('100.000000'))
    assert error.value.code == 'DUPLICATE_CHARGE'
    service.add_rate_charge(session, request.tenant_id, rate_id, ChargeCreate(charge_type='BAF', amount='5', currency='USD', basis='PERCENTAGE', percentage_base='FREIGHT_SUBTOTAL'))
    assert len(service.get_rate_details(session, request.tenant_id, rate_id)['charges']) == 2


def test_duplicates_overlap_ambiguity_and_priority(session, scenario, monkeypatch):
    request, original = scenario
    sheet = new_sheet(session, request, original)
    base = service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id'], status='ACTIVE', charges=[charge('1700')]))
    original_id = UUID(base['rate']['id'])
    with pytest.raises(RateManagementError) as error:
        service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id'], status='ACTIVE', charges=[charge('1700.000000')]))
    assert error.value.code == 'DUPLICATE_RATE'
    monkeypatch.setattr(service, 'utcnow', lambda: session.get(Rate, original_id).created_at)
    with pytest.raises(RateManagementError) as error:
        service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id'], status='ACTIVE', charges=[charge('1600')]))
    assert error.value.code == 'AMBIGUOUS_RATE'
    replacement = service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id'], priority=1, status='ACTIVE', charges=[charge('1600')]))
    assert 'EXACT_OVERLAP' in {w['code'] for w in replacement['warnings']}
    lower = service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id'], priority=-1, status='ACTIVE', charges=[charge('1800')]))
    assert 'LOWER_PRIORITY_OVERLAP' in {w['code'] for w in lower['warnings']}
    assert price_quote(session, request.model_copy(update={'effective_date': date(2026, 11, 15)})).selected_rate_id == UUID(replacement['rate']['id'])


def test_filters_pagination_direction_and_source(session, scenario):
    request, original = scenario
    sheet = new_sheet(session, request, original)
    for priority in (1, 2, 3):
        service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id'], priority=priority,
            source_reference='Entered from carrier email 2026-10-06', charges=[charge(str(1700+priority))]))
    found = service.list_rates(session, request.tenant_id, supplier_id=original.supplier_id, origin=request.origin_location_id,
        destination=request.destination_location_id, equipment=original.equipment_type_id, status='DRAFT',
        mode='OCEAN_FCL', valid_on=date(2026, 11, 15), commercial_type='SPOT', limit=1, offset=1)
    assert found['total'] == 3
    assert found['items'][0]['priority'] == 2
    assert found['items'][0]['source_type'] == 'MANUAL'
    assert found['items'][0]['source_reference'] == 'Entered from carrier email 2026-10-06'
    assert service.list_rates(session, request.tenant_id, origin=request.destination_location_id,
                              destination=request.origin_location_id)['total'] == 0


def test_sheet_validation_and_active_without_charges(session, scenario):
    request, original = scenario
    with pytest.raises(RateManagementError):
        new_sheet(session, request, original, valid_from=date(2026, 11, 30), valid_to=date(2026, 11, 1))
    sheet = new_sheet(session, request, original)
    assert sheet['currency'] == 'USD'
    with pytest.raises(RateManagementError):
        service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id'], status='ACTIVE'))


def test_outer_transaction_rollback_preserves_command_atomicity(session, scenario):
    request, original = scenario
    before = session.scalar(select(func.count()).select_from(RateSheet))
    new_sheet(session, request, original)
    session.rollback()
    assert session.scalar(select(func.count()).select_from(RateSheet)) == before


def test_partial_overlap_and_directional_active_prices(session, scenario):
    request, original = scenario
    sheet = new_sheet(session, request, original)
    first = service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id'],
        status='ACTIVE', charges=[charge('1700')]))
    second = service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id'],
        valid_from=date(2026, 11, 15), valid_to=date(2026, 12, 15), status='ACTIVE', charges=[charge('1600')]))
    assert 'PARTIAL_DATE_OVERLAP' in {item['code'] for item in second['warnings']}
    reverse = service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id'],
        origin_location_id=request.destination_location_id, destination_location_id=request.origin_location_id,
        status='ACTIVE', charges=[charge('1800')]))
    req = request.model_copy(update={'effective_date': date(2026, 11, 10)})
    assert price_quote(session, req).selected_rate_id == UUID(first['rate']['id'])
    assert price_quote(session, req.model_copy(update={'origin_location_id': req.destination_location_id,
        'destination_location_id': req.origin_location_id})).selected_rate_id == UUID(reverse['rate']['id'])


def test_same_lane_two_tenants_have_independent_rates(session, scenario):
    request, original = scenario
    other = create_tenant(session, name='Independent tenant', slug='independent')
    supplier = Supplier(tenant_id=other.id, name='Other carrier', supplier_type='OCEAN_CARRIER')
    session.add(supplier)
    session.flush()
    other_request = request.model_copy(update={'tenant_id': other.id})
    sheet = service.create_rate_sheet(session, other.id, SheetCreate(tenant_id=other.id,
        name='Other October', supplier_id=supplier.id))
    made = service.create_rate(session, other.id, RateCreate(tenant_id=other.id, rate_sheet_id=sheet['id'],
        supplier_id=supplier.id, origin_location_id=request.origin_location_id, destination_location_id=request.destination_location_id,
        equipment_type_id=request.equipment_type_id, valid_from='2026-10-01', valid_to='2026-10-31',
        status='ACTIVE', charges=[charge('1700')]))
    assert price_quote(session, request).buy_total == Decimal('3165.00')
    assert price_quote(session, other_request).buy_total == Decimal('3400.00')
    assert price_quote(session, other_request).selected_rate_id == UUID(made['rate']['id'])
    assert all(item['tenant_id'] == str(other.id) for item in service.list_rates(session, other.id)['items'])


def test_draft_initial_duplicate_charges_rejected(session, scenario):
    request, original = scenario
    sheet = new_sheet(session, request, original)
    with pytest.raises(RateManagementError) as error:
        service.create_rate(session, request.tenant_id, rate_input(request, original, sheet['id'], charges=[charge('100'), charge('100.000000')]))
    assert error.value.code == 'DUPLICATE_CHARGE'


def test_explicit_null_validity_removes_bound_only_in_new_version(session, scenario):
    request, original = scenario
    result = service.create_rate_version(session, request.tenant_id, original.id,
        RateVersion(tenant_id=request.tenant_id, changes={'valid_to': None}))
    successor = session.get(Rate, UUID(result['new_rate_id']))
    assert successor.valid_to is None
    assert original.valid_to == date(2026, 10, 31)
    assert price_quote(session, request.model_copy(update={'effective_date': date(2026, 11, 15)})).status == 'PRICED'


def test_null_commercial_type_is_domain_validation_error(session, scenario):
    request, original = scenario
    with pytest.raises(RateManagementError) as error:
        service.create_rate_version(session, request.tenant_id, original.id,
            RateVersion(tenant_id=request.tenant_id, changes={'commercial_type': None}))
    assert error.value.http_status == 422


def test_management_rejects_other_modes_and_draft_sheet_activation(session, scenario):
    from database.repositories.rate_repository import create_rate_sheet as raw_sheet, create_rate as raw_rate
    request, original = scenario
    road_sheet = raw_sheet(session, request.tenant_id, name='Legacy road', mode='ROAD_FTL', source_type='MANUAL')
    road = raw_rate(session, request.tenant_id, rate_sheet_id=road_sheet.id, mode='ROAD_FTL',
        equipment_type_id=request.equipment_type_id, origin_location_id=request.origin_location_id,
        destination_location_id=request.destination_location_id)
    with pytest.raises(RateManagementError):
        service.deactivate_rate(session, request.tenant_id, road.id)
    assert all(item['mode'] == 'OCEAN_FCL' for item in service.list_rates(session, request.tenant_id)['items'])
    draft_sheet = raw_sheet(session, request.tenant_id, name='Legacy draft', mode='OCEAN_FCL', source_type='MANUAL')
    made = service.create_rate(session, request.tenant_id, rate_input(request, original, draft_sheet.id,
        supplier_id=None, charges=[charge('100')]))
    with pytest.raises(RateManagementError):
        service.update_rate(session, request.tenant_id, UUID(made['rate']['id']),
            RatePatch(tenant_id=request.tenant_id, changes={'status': 'ACTIVE'}))


def test_api_rate_management(session, scenario, monkeypatch):
    from fastapi.testclient import TestClient
    from contextlib import contextmanager
    from api.main import app
    from api.access import internal_access
    import api.rates as routes
    request, original = scenario
    @contextmanager
    def scope(*args):
        yield session
    monkeypatch.setattr(routes, 'session_scope', scope)
    monkeypatch.setattr(routes, 'get_engine', lambda: None)
    monkeypatch.setitem(app.dependency_overrides, internal_access, lambda: None)
    with TestClient(app) as client:
        response = client.post('/admin/rates/sheets', json={'tenant_id': str(request.tenant_id), 'supplier_id': str(original.supplier_id), 'name': 'api rates'})
        assert response.status_code == 200
        payload = rate_input(request, original, response.json()['id']).model_dump(mode='json')
        response = client.post('/admin/rates', json=payload)
        assert response.status_code == 200
        rate_id = response.json()['rate']['id']
        assert client.get('/admin/rates').status_code == 422
        assert client.get(f'/admin/rates/{rate_id}', params={'tenant_id': str(uuid4())}).status_code == 404
        assert client.post(f'/admin/rates/{rate_id}/charges', json={'tenant_id': str(request.tenant_id), **charge().model_dump(mode='json')}).status_code == 200
        assert client.post(f'/admin/rates/{rate_id}/update', json={'tenant_id': str(request.tenant_id), 'changes': {'status': 'ACTIVE'}}).status_code == 200
        assert client.get('/admin/rates', params={'tenant_id': str(request.tenant_id), 'status': 'ACTIVE'}).json()['total'] == 2
        assert client.post('/admin/rates', json={**payload, 'mode': 'AIR'}).status_code == 422
        assert client.post(f'/admin/rates/{rate_id}/deactivate', json={'tenant_id': str(request.tenant_id)}).status_code == 200
