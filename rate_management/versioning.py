from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from contextlib import contextmanager
from database.models import RateEvent
from rate_management.exceptions import RateManagementError

METADATA_FIELDS = {"notes", "market_notes", "capacity_notes", "service_frequency_notes", "disruption_notes"}
STATE_FIELDS = {"status", "is_active"}


def json_value(value):
    if isinstance(value, (date, datetime, Decimal, UUID)):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def diff(old, new):
    return [{"field": key, "old": json_value(old.get(key)), "new": json_value(new.get(key))}
            for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key)]


def audit(session, tenant_id, action, old_id, new_id, changes):
    session.add(RateEvent(tenant_id=tenant_id, action=action, old_rate_id=old_id,
                          new_rate_id=new_id, changes=json_value(changes)))
    session.flush()


@contextmanager
def controlled_edit(session, row, fields):
    if not set(fields) <= METADATA_FIELDS | STATE_FIELDS:
        raise RateManagementError("Economic edits require a version")
    permissions = session.info.setdefault("_rate_management_writes", {})
    permissions[id(row)] = set(fields)
    try:
        yield
        session.flush()
    finally:
        permissions.pop(id(row), None)
