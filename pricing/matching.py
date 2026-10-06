from sqlalchemy import select

from database.models import LocationGroupMember


def location_groups(session, tenant_id, location_id):
    return set(session.scalars(select(LocationGroupMember.location_group_id).where(
        LocationGroupMember.tenant_id == tenant_id, LocationGroupMember.location_id == location_id)))


def applicable_dates(row, effective_date):
    return ((row.valid_from is None or row.valid_from <= effective_date)
            and (row.valid_to is None or row.valid_to >= effective_date))


def matches_target(location_id, group_id, requested_id, groups):
    if location_id is not None:
        return location_id == requested_id
    if group_id is not None:
        return group_id in groups
    return True  # Rule wildcard, never used to infer a rate lane.
