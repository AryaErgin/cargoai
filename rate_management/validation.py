from datetime import date
import re
from sqlalchemy import select
from database.models import Tenant, Supplier, Location, LocationGroup, EquipmentType, ChargeType, RateSheet
from rate_management.exceptions import RateManagementError, NotFound


def owned(session, model, tenant_id, row_id):
    row = session.scalar(select(model).where(model.tenant_id == tenant_id, model.id == row_id))
    if row is None:
        raise NotFound()
    return row


def tenant(session, tenant_id):
    row = session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if row is None or not row.is_active:
        raise NotFound()
    return row


def validity(start, end):
    if start is not None and end is not None and end < start:
        raise RateManagementError("valid_to must be on or after valid_from")


def currency(value, *, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{3}", value):
        raise RateManagementError("Currency must be a three-letter code")
    return value.upper()


def equipment(session, equipment_id):
    if equipment_id is None:
        raise RateManagementError("Equipment is required")
    row = session.get(EquipmentType, equipment_id)
    if row is None or row.transport_mode != "OCEAN" or not row.supported or row.canonical_code not in {"20GP", "40GP", "40HC"}:
        raise RateManagementError("V1 supports only ocean 20GP, 40GP and 40HC equipment")
    return row


def sheet(session, tenant_id, values):
    validity(values.get("valid_from"), values.get("valid_to"))
    if values["mode"] != "OCEAN_FCL" or values["source_type"] != "MANUAL":
        raise RateManagementError("V1 supports only manual OCEAN_FCL rate sheets")
    if values.get("commercial_type") not in {"SPOT", "CONTRACT"}:
        raise RateManagementError("Supplier commercial type must be SPOT or CONTRACT")
    if not values["name"].strip():
        raise RateManagementError("Rate sheet name must not be blank")
    if values.get("supplier_id"):
        owned(session, Supplier, tenant_id, values["supplier_id"])
    values["currency"] = currency(values.get("currency"), nullable=True)


def rate(session, tenant_id, values, parent):
    if values["mode"] != "OCEAN_FCL" or parent.mode != "OCEAN_FCL":
        raise RateManagementError("V1 supports only OCEAN_FCL rates")
    if values.get("priority") is None:
        raise RateManagementError("Priority cannot be null")
    if parent.source_type != "MANUAL":
        raise RateManagementError("Manual management requires a MANUAL rate sheet")
    if values.get("commercial_type") not in {"SPOT", "CONTRACT"} or values["commercial_type"] != parent.commercial_type:
        raise RateManagementError("Supplier rate commercial type must match its sheet; CUSTOMER_FIXED is not a buy rate")
    if values.get("supplier_id") != parent.supplier_id:
        raise RateManagementError("Rate supplier must match its sheet supplier")
    if values.get("supplier_id"):
        owned(session, Supplier, tenant_id, values["supplier_id"])
    equipment(session, values["equipment_type_id"])
    for side in ("origin", "destination"):
        location_id, group_id = values.get(f"{side}_location_id"), values.get(f"{side}_group_id")
        if bool(location_id) == bool(group_id):
            raise RateManagementError(f"Exactly one {side} location/group is required")
        if location_id and session.get(Location, location_id) is None:
            raise RateManagementError(f"Unknown {side} location")
        if group_id:
            owned(session, LocationGroup, tenant_id, group_id)
    # Explicitly materialize inherited sheet boundaries so successor snapshots
    # retain the actual old applicability, not an accidental open-ended rate.
    for field in ("valid_from", "valid_to"):
        if values.get(field) is None:
            values[field] = getattr(parent, field)
    validity(values.get("valid_from"), values.get("valid_to"))
    if parent.valid_from and (values["valid_from"] is None or values["valid_from"] < parent.valid_from):
        raise RateManagementError("Rate validity starts before its sheet")
    if parent.valid_to and (values["valid_to"] is None or values["valid_to"] > parent.valid_to):
        raise RateManagementError("Rate validity ends after its sheet")
    if values.get("status") not in {"DRAFT", "ACTIVE", "EXPIRED", "ARCHIVED"}:
        raise RateManagementError("Invalid rate status")
    values["is_active"] = values["status"] == "ACTIVE"


def charge(session, tenant_id, model, parent):
    values = model.model_dump()
    charge_type = session.scalar(select(ChargeType).where(ChargeType.canonical_code == values.pop("charge_type").upper()))
    if charge_type is None:
        raise RateManagementError("Unknown charge type")
    values["charge_type_id"] = charge_type.id
    values["currency"] = currency(values["currency"])
    validity(values["valid_from"], values["valid_to"])
    for field in ("minimum_amount", "maximum_amount"):
        if values[field] is not None and values[field] < 0:
            raise RateManagementError("Charge bounds must be nonnegative")
    if values["minimum_amount"] is not None and values["maximum_amount"] is not None and values["minimum_amount"] > values["maximum_amount"]:
        raise RateManagementError("Minimum amount exceeds maximum amount")
    if values["basis"] == "PERCENTAGE":
        if values["percentage_base"] not in {"FREIGHT_SUBTOTAL", "BUY_SUBTOTAL"} or values["amount"] > 100:
            raise RateManagementError("Percentage charges require an explicit subtotal and a value from 0 to 100")
    elif values["percentage_base"] is not None:
        raise RateManagementError("percentage_base is only valid for percentage charges")
    if values["equipment_type_id"]:
        equipment(session, values["equipment_type_id"])
        if values["equipment_type_id"] != parent.equipment_type_id:
            raise RateManagementError("Charge equipment must match its rate")
    if parent.valid_from and values["valid_from"] and values["valid_from"] < parent.valid_from:
        raise RateManagementError("Charge validity starts before its rate")
    if parent.valid_to and values["valid_to"] and values["valid_to"] > parent.valid_to:
        raise RateManagementError("Charge validity ends after its rate")
    if (parent.valid_from and values["valid_to"] and values["valid_to"] < parent.valid_from) or (parent.valid_to and values["valid_from"] and values["valid_from"] > parent.valid_to):
        raise RateManagementError("Charge validity does not intersect its rate")
    return values


def intersection(rate, sheet):
    return (max(v for v in (rate.valid_from, sheet.valid_from, date.min) if v is not None),
            min(v for v in (rate.valid_to, sheet.valid_to, date.max) if v is not None))
