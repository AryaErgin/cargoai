"""RFQ response deadlines and overdue flags (deterministic; callers inject `now` for tests)."""
from datetime import datetime, timedelta

from sourcing import config

OVERDUE_STATUSES = frozenset({"APPROVED", "SENT"})


def _aware(value, name):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def response_due_at(created_at, hours=None):
    hours = config.response_hours() if hours is None else hours
    return _aware(created_at, "created_at") + timedelta(hours=hours)


def is_overdue(rfq, now):
    """APPROVED/SENT RFQs past their deadline without a reply (REPLIED is never overdue)."""
    now = _aware(now, "now")
    return rfq.status in OVERDUE_STATUSES and now > rfq.response_due_at


def count_overdue(rfqs, now):
    return sum(1 for rfq in rfqs if is_overdue(rfq, now))
