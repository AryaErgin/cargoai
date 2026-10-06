from datetime import date
from uuid import UUID

from sqlalchemy import inspect, or_, select

from database.models import Rate, RateCharge, RateSheet, LocationGroupMember
from database.repositories._scoped import create_owned, get_owned, scoped_statement, require_tenant


def create_rate_sheet(session, tenant_id, **values):
    if values.get("parent_rate_sheet_id") is not None or values.get("version", 1) != 1:
        raise ValueError("Use create_rate_sheet_version for successor versions")
    return create_owned(session, RateSheet, tenant_id, values)


def create_rate(session, tenant_id, **values):
    return create_owned(session, Rate, tenant_id, values)


def get_rate(session, tenant_id, rate_id):
    return get_owned(session, Rate, tenant_id, rate_id)


def create_rate_charge(session, tenant_id, **values):
    return create_owned(session, RateCharge, tenant_id, values)


def list_rate_charges(session, tenant_id, rate_id):
    return list(session.scalars(scoped_statement(RateCharge, tenant_id).where(RateCharge.rate_id == rate_id).order_by(RateCharge.id)))


def list_rates(session, tenant_id, *, mode=None, supplier_id=None, rate_sheet_id=None, limit=100, offset=0):
    if not 1 <= limit <= 1000 or offset < 0:
        raise ValueError("limit must be 1..1000 and offset nonnegative")
    query = scoped_statement(Rate, tenant_id)
    for column, value in ((Rate.mode, mode), (Rate.supplier_id, supplier_id), (Rate.rate_sheet_id, rate_sheet_id)):
        if value is not None:
            query = query.where(column == value)
    return list(session.scalars(query.order_by(Rate.id).limit(limit).offset(offset)))


def date_conditions(model, effective_date):
    return (or_(model.valid_from.is_(None), model.valid_from <= effective_date),
            or_(model.valid_to.is_(None), model.valid_to >= effective_date))


def find_candidate_rates(session, tenant_id, mode, origin_location_id, destination_location_id, equipment_type_id, effective_date):
    """Return all applicable candidates without pricing or selection ranking.

    NULL equipment applies to all equipment. A missing origin/destination target
    remains stored but is never treated as an implicit wildcard route.
    """
    require_tenant(tenant_id)
    if not isinstance(origin_location_id, UUID) or not isinstance(destination_location_id, UUID):
        raise ValueError("Origin and destination must be explicit location UUIDs")
    if not isinstance(effective_date, date):
        raise ValueError("effective_date must be a date")
    origin_groups = select(LocationGroupMember.location_group_id).where(
        LocationGroupMember.tenant_id == tenant_id, LocationGroupMember.location_id == origin_location_id)
    destination_groups = select(LocationGroupMember.location_group_id).where(
        LocationGroupMember.tenant_id == tenant_id, LocationGroupMember.location_id == destination_location_id)
    query = scoped_statement(Rate, tenant_id).join(
        RateSheet, (RateSheet.id == Rate.rate_sheet_id) & (RateSheet.tenant_id == Rate.tenant_id)
    ).where(
        Rate.is_active.is_(True), Rate.mode == mode, RateSheet.status == "ACTIVE",
        or_(Rate.origin_location_id == origin_location_id, Rate.origin_group_id.in_(origin_groups)),
        or_(Rate.destination_location_id == destination_location_id, Rate.destination_group_id.in_(destination_groups)),
        or_(Rate.equipment_type_id == equipment_type_id, Rate.equipment_type_id.is_(None)),
        *date_conditions(Rate, effective_date), *date_conditions(RateSheet, effective_date),
    )
    return list(session.scalars(query.order_by(Rate.id)))


def snapshot_values(row):
    return {column.key: getattr(row, column.key) for column in inspect(type(row)).columns
            if column.key not in {"id", "tenant_id", "created_at", "updated_at"}}


def create_rate_sheet_version(session, tenant_id, parent_rate_sheet_id, *, sheet_changes=None,
                              rate_changes=None, charge_changes=None):
    """Clone a sheet/rates/charges to new UUIDs; old quote references remain valid.

    Changes are dictionaries keyed by original rate or charge UUID. Callers own
    the transaction. A parent has one successor; duplicate/concurrent successors
    are rejected rather than silently branching a version chain.
    """
    parent = get_owned(session, RateSheet, tenant_id, parent_rate_sheet_id)
    if parent is None:
        raise ValueError("Rate sheet was not found for this tenant")
    sheet_changes = sheet_changes or {}
    rate_changes = rate_changes or {}
    charge_changes = charge_changes or {}
    for changes in [sheet_changes, *rate_changes.values(), *charge_changes.values()]:
        if {"id", "tenant_id", "created_at", "updated_at", "version", "parent_rate_sheet_id", "rate_sheet_id", "rate_id"} & changes.keys():
            raise ValueError("Version identity and ownership cannot be overridden")
    rates = list(session.scalars(scoped_statement(Rate, tenant_id).where(Rate.rate_sheet_id == parent.id)))
    charges = list(session.scalars(scoped_statement(RateCharge, tenant_id).where(RateCharge.rate_id.in_([r.id for r in rates]))))
    if not rate_changes.keys() <= {r.id for r in rates} or not charge_changes.keys() <= {c.id for c in charges}:
        raise ValueError("Changes must reference rates/charges in this tenant's source sheet")
    values = snapshot_values(parent)
    values.update(sheet_changes, version=parent.version + 1, parent_rate_sheet_id=parent.id)
    successor = create_owned(session, RateSheet, tenant_id, values)
    copied_rates = {}
    for old_rate in rates:
        values = snapshot_values(old_rate)
        values.update(rate_changes.get(old_rate.id, {}), rate_sheet_id=successor.id)
        copied_rates[old_rate.id] = create_rate(session, tenant_id, **values)
    for old_charge in charges:
        values = snapshot_values(old_charge)
        values.update(charge_changes.get(old_charge.id, {}), rate_id=copied_rates[old_charge.rate_id].id)
        create_rate_charge(session, tenant_id, **values)
    return successor
