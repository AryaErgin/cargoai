"""Transactional, tenant-scoped commands. Importers must call these services."""
from functools import wraps
from uuid import UUID
from pydantic import ValidationError
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from database.base import utcnow
from database.models import (Rate, RateSheet, RateCharge, RateEvent, Supplier, Location,
    LocationGroup, LocationGroupMember, EquipmentType, ChargeType)
from database.repositories.rate_repository import snapshot_values
from pricing.rate_selector import _rank
from rate_management.models import SheetCreate, RateCreate, ChargeCreate, RateVersion, RatePatch
from rate_management.exceptions import RateManagementError, Conflict
from rate_management import validation as v
from rate_management.versioning import METADATA_FIELDS, json_value, diff, audit, controlled_edit


def command(function):
    @wraps(function)
    def run(session, tenant_id, *args, **kwargs):
        if not isinstance(tenant_id, UUID):
            raise RateManagementError("An explicit tenant UUID is required")
        try:
            # sqlite3 legacy transaction control does not BEGIN for SELECTs or
            # SAVEPOINTs. Ensure releasing the command savepoint cannot commit
            # before the caller's outer unit of work succeeds.
            connection = session.connection()
            if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql("BEGIN")
            with session.begin_nested():
                v.tenant(session, tenant_id)
                return function(session, tenant_id, *args, **kwargs)
        except ValidationError as error:
            raise RateManagementError("Invalid rate management input", metadata={"errors": error.errors(include_context=False, include_input=False)}) from None
        except IntegrityError:
            raise Conflict("Concurrent/conflicting rate write; reload and retry") from None
    return run


def _input(model, request, tenant_id):
    request = model.model_validate(request.model_dump(exclude_unset=True) if hasattr(request, "model_dump") else request)
    if hasattr(request, "tenant_id") and request.tenant_id != tenant_id:
        raise RateManagementError("Request tenant_id must match the service scope")
    return request


def _charges(session, tenant_id, rate_id):
    return list(session.scalars(select(RateCharge).where(RateCharge.tenant_id == tenant_id,
                                                       RateCharge.rate_id == rate_id).order_by(RateCharge.id)))


def _managed_rate(session, tenant_id, rate_id):
    row = v.owned(session, Rate, tenant_id, rate_id)
    if row.mode != "OCEAN_FCL":
        raise RateManagementError("V1 manages only OCEAN_FCL rates")
    v.equipment(session, row.equipment_type_id)
    return row


def _charge_input(session, charge):
    values = snapshot_values(charge)
    values.pop("rate_id")
    values["charge_type"] = session.get(ChargeType, values.pop("charge_type_id")).canonical_code
    return values


def _fingerprint(session, tenant_id, rate_id):
    from decimal import Decimal
    def normalized(values):
        return json_value({key: format(value.normalize(), 'f') if isinstance(value, Decimal) else value
                           for key, value in values.items() if key not in {"rate_id", "notes"}})
    return sorted(repr(sorted(normalized(snapshot_values(c)).items())) for c in _charges(session, tenant_id, rate_id))


def _targets(session, tenant_id, rate, side):
    location = getattr(rate, f"{side}_location_id")
    if location:
        return {location}
    return set(session.scalars(select(LocationGroupMember.location_id).where(
        LocationGroupMember.tenant_id == tenant_id,
        LocationGroupMember.location_group_id == getattr(rate, f"{side}_group_id"))))


def _check_conflicts(session, tenant_id, rate, *, ignore_id=None):
    parent = v.owned(session, RateSheet, tenant_id, rate.rate_sheet_id)
    warnings = []
    # Consider intersecting groups as well as identical target IDs. Direction is
    # preserved: origin is compared with origin, never with destination.
    rows = session.execute(select(Rate, RateSheet).join(RateSheet,
        (RateSheet.id == Rate.rate_sheet_id) & (RateSheet.tenant_id == Rate.tenant_id)).where(
        Rate.tenant_id == tenant_id, Rate.mode == rate.mode,
        Rate.equipment_type_id == rate.equipment_type_id, Rate.id != rate.id)).all()
    lane_fields = ("origin_location_id", "origin_group_id", "destination_location_id", "destination_group_id")
    start, end = v.intersection(rate, parent)
    for other, sheet in rows:
        same_lane = all(getattr(rate, key) == getattr(other, key) for key in lane_fields)
        a, b = v.intersection(other, sheet)
        same_period = (start, end) == (a, b)
        # Duplicate economics cannot be smuggled in as a higher priority/version.
        if other.id != ignore_id and same_lane and same_period and other.supplier_id == rate.supplier_id and other.commercial_type == rate.commercial_type and _fingerprint(session, tenant_id, other.id) == _fingerprint(session, tenant_id, rate.id):
            raise Conflict("Exact duplicate manual rate", code="DUPLICATE_RATE", metadata={"existing_rate_id": str(other.id)})
        if end < a or b < start:
            continue
        if not same_lane and (not (_targets(session, tenant_id, rate, "origin") & _targets(session, tenant_id, other, "origin")) or
                              not (_targets(session, tenant_id, rate, "destination") & _targets(session, tenant_id, other, "destination"))):
            continue
        rank, _ = _rank(rate, parent)
        other_rank, _ = _rank(other, sheet)
        if rate.is_active and parent.status == "ACTIVE" and other.is_active and sheet.status == "ACTIVE" and rank == other_rank:
            raise Conflict("Rate would create indistinguishable pricing candidates", code="AMBIGUOUS_RATE",
                           metadata={"existing_rate_id": str(other.id)})
        if other.supplier_id == rate.supplier_id and rank[0] == other_rank[0]:
            warning = "EXACT_OVERLAP" if same_period else "PARTIAL_DATE_OVERLAP"
            warnings.append({"code": warning, "rate_id": str(other.id)})
            if rate.priority < other.priority:
                warnings.append({"code": "LOWER_PRIORITY_OVERLAP", "rate_id": str(other.id)})
    return warnings


def _ensure_priceable(session, tenant_id, rate):
    if rate.status == "ACTIVE" and v.owned(session, RateSheet, tenant_id, rate.rate_sheet_id).status != "ACTIVE":
        raise RateManagementError("An ACTIVE rate requires an ACTIVE sheet")
    if rate.status == "ACTIVE" and not any(c.mandatory for c in _charges(session, tenant_id, rate.id)):
        raise RateManagementError("An ACTIVE rate requires at least one mandatory charge")


@command
def create_rate_sheet(session, tenant_id, request):
    request = _input(SheetCreate, request, tenant_id)
    values = request.model_dump(exclude={"tenant_id"})
    v.sheet(session, tenant_id, values)
    row = RateSheet(tenant_id=tenant_id, status="ACTIVE", **values)
    session.add(row)
    session.flush()
    audit(session, tenant_id, "CREATE_SHEET", None, None, [{"field": "rate_sheet", "old": None, "new": json_value({"id": row.id, **values})}])
    return json_value({"id": row.id, "tenant_id": tenant_id, "status": row.status, **values})


@command
def create_rate(session, tenant_id, request):
    request = _input(RateCreate, request, tenant_id)
    values = request.model_dump(exclude={"tenant_id", "charges"})
    parent = v.owned(session, RateSheet, tenant_id, request.rate_sheet_id)
    if "supplier_id" not in request.model_fields_set:
        values["supplier_id"] = parent.supplier_id
    v.rate(session, tenant_id, values, parent)
    row = Rate(tenant_id=tenant_id, created_at=utcnow(), **values)
    session.add(row)
    session.flush()
    for item in request.charges:
        session.add(RateCharge(tenant_id=tenant_id, rate_id=row.id, **v.charge(session, tenant_id, item, row)))
    session.flush()
    fingerprints = _fingerprint(session, tenant_id, row.id)
    if len(fingerprints) != len(set(fingerprints)):
        raise Conflict("Exact duplicate charge", code="DUPLICATE_CHARGE")
    _ensure_priceable(session, tenant_id, row)
    warnings = _check_conflicts(session, tenant_id, row)
    audit(session, tenant_id, "CREATE_RATE", None, row.id, diff({}, snapshot_values(row)))
    return {"rate": get_rate_details(session, tenant_id, row.id), "warnings": warnings}


@command
def add_rate_charge(session, tenant_id, rate_id, request):
    request = _input(ChargeCreate, request, tenant_id)
    row = _managed_rate(session, tenant_id, rate_id)
    if row.status != "DRAFT":
        return create_rate_version(session, tenant_id, row.id, RateVersion(tenant_id=tenant_id,
            changes={}, additional_charges=[request]))
    values = v.charge(session, tenant_id, request, row)
    if any({k: value for k, value in snapshot_values(c).items() if k not in {"rate_id", "notes"}} ==
           {k: value for k, value in values.items() if k != "notes"} for c in _charges(session, tenant_id, row.id)):
        raise Conflict("Exact duplicate charge", code="DUPLICATE_CHARGE")
    charge = RateCharge(tenant_id=tenant_id, rate_id=row.id, **values)
    session.add(charge)
    session.flush()
    warnings = _check_conflicts(session, tenant_id, row)
    audit(session, tenant_id, "ADD_DRAFT_CHARGE", row.id, row.id, diff({}, values))
    return {"rate": get_rate_details(session, tenant_id, row.id), "warnings": warnings}


@command
def update_rate(session, tenant_id, rate_id, request):
    request = _input(RatePatch, request, tenant_id)
    row = _managed_rate(session, tenant_id, rate_id)
    changes = request.changes.model_dump(exclude_unset=True)
    if not changes:
        raise RateManagementError("No changes supplied")
    if not changes.keys() <= METADATA_FIELDS | {"status"}:
        return create_rate_version(session, tenant_id, rate_id, RateVersion(tenant_id=tenant_id, changes=changes))
    if "status" in changes and changes["status"] is None:
        raise RateManagementError("status cannot be null")
    if row.status == "ARCHIVED" and changes.get("status", "ARCHIVED") != "ARCHIVED":
        raise Conflict("Archived rates cannot be reactivated; create a successor")
    old = snapshot_values(row)
    if "status" in changes:
        changes["is_active"] = changes["status"] == "ACTIVE"
    with controlled_edit(session, row, changes):
        for field, value in changes.items():
            setattr(row, field, value)
    _ensure_priceable(session, tenant_id, row)
    warnings = _check_conflicts(session, tenant_id, row)
    audit(session, tenant_id, "UPDATE_METADATA_STATUS", row.id, row.id, diff(old, snapshot_values(row)))
    return {"rate": get_rate_details(session, tenant_id, row.id), "warnings": warnings}


@command
def deactivate_rate(session, tenant_id, rate_id, *, status="ARCHIVED"):
    if status not in {"EXPIRED", "ARCHIVED"}:
        raise RateManagementError("Deactivation status must be EXPIRED or ARCHIVED")
    return update_rate(session, tenant_id, rate_id, RatePatch(tenant_id=tenant_id, changes={"status": status}))


@command
def create_rate_version(session, tenant_id, rate_id, request):
    request = _input(RateVersion, request, tenant_id)
    old = _managed_rate(session, tenant_id, rate_id)
    if session.scalar(select(RateEvent.id).where(RateEvent.tenant_id == tenant_id,
            RateEvent.old_rate_id == old.id, RateEvent.action == "CREATE_VERSION")):
        raise Conflict("This rate already has a successor; update its latest version", code="STALE_VERSION")
    source_sheet = v.owned(session, RateSheet, tenant_id, old.rate_sheet_id)
    old_values = snapshot_values(old)
    values = dict(old_values)
    changes = request.changes.model_dump(exclude_unset=True)
    values.update(changes)
    if values.get("valid_from") is None and "valid_from" not in changes:
        values["valid_from"] = source_sheet.valid_from
    if values.get("valid_to") is None and "valid_to" not in changes:
        values["valid_to"] = source_sheet.valid_to
    sheet_values = snapshot_values(source_sheet)
    # Each successor is a single-rate snapshot, not a mutation of other lanes.
    tail = source_sheet
    while True:
        next_sheet = session.scalar(select(RateSheet).where(RateSheet.tenant_id == tenant_id,
                                      RateSheet.parent_rate_sheet_id == tail.id))
        if next_sheet is None:
            break
        tail = next_sheet
    sheet_values.update(parent_rate_sheet_id=tail.id, version=tail.version + 1,
        supplier_id=values["supplier_id"], commercial_type=values["commercial_type"],
        valid_from=values["valid_from"], valid_to=values["valid_to"], source_type="MANUAL", status="ACTIVE")
    v.sheet(session, tenant_id, sheet_values)
    sheet = RateSheet(tenant_id=tenant_id, **sheet_values)
    session.add(sheet)
    session.flush()
    values["rate_sheet_id"] = sheet.id
    v.rate(session, tenant_id, values, sheet)
    row = Rate(tenant_id=tenant_id, created_at=utcnow(), **values)
    session.add(row)
    session.flush()
    old_charges = _charges(session, tenant_id, old.id)
    if not request.charge_changes.keys() <= {c.id for c in old_charges}:
        raise RateManagementError("Charge changes must reference this tenant's source rate")
    charge_diffs = []
    for old_charge in old_charges:
        original = _charge_input(session, old_charge)
        updated = {**original, **request.charge_changes.get(old_charge.id, {})}
        model = ChargeCreate.model_validate(updated)
        validated = v.charge(session, tenant_id, model, row)
        session.add(RateCharge(tenant_id=tenant_id, rate_id=row.id, **validated))
        for item in diff(original, model.model_dump()):
            item["field"] = f"{original['charge_type']}[{old_charge.id}].{item['field']}"
            charge_diffs.append(item)
    for item in request.additional_charges:
        validated = v.charge(session, tenant_id, item, row)
        session.add(RateCharge(tenant_id=tenant_id, rate_id=row.id, **validated))
        charge_diffs.append({"field": item.charge_type, "old": None, "new": json_value(item.model_dump())})
    session.flush()
    new_fingerprint = _fingerprint(session, tenant_id, row.id)
    if len(new_fingerprint) != len(set(new_fingerprint)):
        raise Conflict("Exact duplicate charge in successor", code="DUPLICATE_CHARGE")
    differences = diff({k: val for k, val in old_values.items() if k != "rate_sheet_id"},
                       {k: val for k, val in snapshot_values(row).items() if k != "rate_sheet_id"}) + charge_diffs
    if not differences:
        raise Conflict("No effective changes; refusing an identical successor", code="DUPLICATE_RATE")
    _ensure_priceable(session, tenant_id, row)
    warnings = _check_conflicts(session, tenant_id, row, ignore_id=old.id)
    audit(session, tenant_id, "CREATE_VERSION", old.id, row.id, differences)
    return {"old_rate_id": str(old.id), "new_rate_id": str(row.id), "changes": differences,
            "rate": get_rate_details(session, tenant_id, row.id), "warnings": warnings}


def get_rate_details(session, tenant_id, rate_id):
    if not isinstance(tenant_id, UUID):
        raise RateManagementError("An explicit tenant UUID is required")
    row = _managed_rate(session, tenant_id, rate_id)
    sheet = v.owned(session, RateSheet, tenant_id, row.rate_sheet_id)
    supplier = v.owned(session, Supplier, tenant_id, row.supplier_id) if row.supplier_id else None
    result = {"id": row.id, "tenant_id": tenant_id, **snapshot_values(row), "source_type": sheet.source_type,
              "version": sheet.version, "supplier": None if supplier is None else {"id": supplier.id, "name": supplier.name}}
    for side in ("origin", "destination"):
        group_id = getattr(row, f"{side}_group_id")
        target = v.owned(session, LocationGroup, tenant_id, group_id) if group_id else session.get(Location, getattr(row, f"{side}_location_id"))
        result[side] = None if target is None else {"id": target.id, "name": target.name, "type": "group" if group_id else "location"}
    equip = session.get(EquipmentType, row.equipment_type_id)
    result["equipment"] = None if equip is None else {"id": equip.id, "code": equip.canonical_code}
    charges = []
    for item in _charges(session, tenant_id, row.id):
        kind = session.get(ChargeType, item.charge_type_id)
        charges.append({"id": item.id, **snapshot_values(item), "charge_type": kind.canonical_code, "category": kind.category})
    result["charges"] = charges
    result["charge_metadata"] = {"count": len(charges), "mandatory_count": sum(c["mandatory"] for c in charges),
                                "currencies": sorted({c["currency"] for c in charges}),
                                "bases": sorted({c["basis"] for c in charges})}
    links = list(session.scalars(select(RateEvent).where(RateEvent.tenant_id == tenant_id,
        RateEvent.action == "CREATE_VERSION", or_(RateEvent.old_rate_id == row.id, RateEvent.new_rate_id == row.id))))
    result["previous_version_ids"] = [event.old_rate_id for event in links if event.new_rate_id == row.id]
    result["newer_version_ids"] = [event.new_rate_id for event in links if event.old_rate_id == row.id]
    return json_value(result)


def list_rates(session, tenant_id, *, supplier_id=None, origin=None, destination=None, equipment=None,
               mode=None, status=None, valid_on=None, commercial_type=None, limit=50, offset=0):
    if not isinstance(tenant_id, UUID):
        raise RateManagementError("An explicit tenant UUID is required")
    v.tenant(session, tenant_id)
    if not 1 <= limit <= 1000 or offset < 0:
        raise RateManagementError("limit must be 1..1000; offset must be nonnegative")
    if mode is not None and mode != "OCEAN_FCL":
        raise RateManagementError("V1 manages only OCEAN_FCL rates")
    supported = select(EquipmentType.id).where(EquipmentType.transport_mode == "OCEAN",
        EquipmentType.supported.is_(True), EquipmentType.canonical_code.in_(["20GP", "40GP", "40HC"]))
    query = select(Rate).join(RateSheet, (Rate.rate_sheet_id == RateSheet.id) & (Rate.tenant_id == RateSheet.tenant_id)).where(
        Rate.tenant_id == tenant_id, Rate.mode == "OCEAN_FCL", Rate.equipment_type_id.in_(supported))
    for column, value in ((Rate.supplier_id, supplier_id), (Rate.equipment_type_id, equipment),
        (Rate.mode, mode), (Rate.status, status), (Rate.commercial_type, commercial_type)):
        if value is not None:
            query = query.where(column == value)
    for side, value in (("origin", origin), ("destination", destination)):
        if value is not None:
            groups = select(LocationGroupMember.location_group_id).where(LocationGroupMember.tenant_id == tenant_id,
                                                                         LocationGroupMember.location_id == value)
            query = query.where(or_(getattr(Rate, f"{side}_location_id") == value,
                                   getattr(Rate, f"{side}_group_id") == value,
                                   getattr(Rate, f"{side}_group_id").in_(groups)))
    if valid_on is not None:
        for model in (Rate, RateSheet):
            query = query.where(or_(model.valid_from.is_(None), model.valid_from <= valid_on),
                                or_(model.valid_to.is_(None), model.valid_to >= valid_on))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.scalars(query.order_by(Rate.priority.desc(), RateSheet.version.desc(), Rate.created_at.desc(), Rate.id).limit(limit).offset(offset))
    return {"total": total, "limit": limit, "offset": offset,
            "items": [get_rate_details(session, tenant_id, row.id) for row in rows]}
