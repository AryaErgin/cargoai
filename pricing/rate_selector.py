from datetime import date

from sqlalchemy import or_, select

from database.models import Rate, RateSheet
from pricing.exceptions import AmbiguousRate, NoRateFound
from pricing.matching import applicable_dates, location_groups


SPECIFICITIES = {1: "exact_origin_exact_destination", 2: "exact_origin_destination_group",
                 3: "origin_group_exact_destination", 4: "origin_group_destination_group"}
RANK_COMPONENTS = ["specificity", "priority", "validity_width", "validity_start", "sheet_version", "created_at"]


def _rank(rate, sheet):
    specificity = (1 if rate.destination_location_id else 2) if rate.origin_location_id else (3 if rate.destination_location_id else 4)
    start = max(value for value in (rate.valid_from, sheet.valid_from, date.min) if value is not None)
    end = min(value for value in (rate.valid_to, sheet.valid_to, date.max) if value is not None)
    width = (end - start).days
    return (-specificity, rate.priority, -width, start.toordinal(), sheet.version, rate.created_at), {
        "specificity_level": specificity, "specificity": SPECIFICITIES[specificity],
        "priority": rate.priority, "effective_valid_from": None if start == date.min else start.isoformat(),
        "effective_valid_to": None if end == date.max else end.isoformat(),
        "validity_width_days": width, "rate_sheet_id": str(sheet.id), "rate_sheet_version": sheet.version,
        "created_at": rate.created_at.isoformat()}


def select_rate(session, request):
    origins = location_groups(session, request.tenant_id, request.origin_location_id)
    destinations = location_groups(session, request.tenant_id, request.destination_location_id)
    query = select(Rate, RateSheet).join(RateSheet,
        (RateSheet.id == Rate.rate_sheet_id) & (RateSheet.tenant_id == Rate.tenant_id)).where(
        Rate.tenant_id == request.tenant_id, Rate.mode == request.mode,
        or_(Rate.origin_location_id == request.origin_location_id, Rate.origin_group_id.in_(origins)),
        or_(Rate.destination_location_id == request.destination_location_id, Rate.destination_group_id.in_(destinations)))
    eligible, rejected = [], []
    for rate, sheet in session.execute(query):
        reasons = []
        if not rate.is_active:
            reasons.append("inactive_rate")
        if rate.equipment_type_id != request.equipment_type_id:
            reasons.append("equipment_mismatch")
        if sheet.status != "ACTIVE" or sheet.mode != request.mode:
            reasons.append("inapplicable_rate_sheet")
        if not applicable_dates(rate, request.effective_date):
            reasons.append("rate_outside_validity")
        if not applicable_dates(sheet, request.effective_date):
            reasons.append("sheet_outside_validity")
        if reasons:
            rejected.append({"rate_id": str(rate.id), "reasons": reasons})
        else:
            key, metadata = _rank(rate, sheet)
            eligible.append((key, rate, sheet, metadata))
    rejected.sort(key=lambda value: value["rate_id"])
    if not eligible:
        raise NoRateFound("No eligible ocean-FCL rate for the requested lane, equipment and date",
                           metadata={"rejected_candidates": rejected})
    eligible.sort(key=lambda value: value[0], reverse=True)
    winner = eligible[0]
    tied = [item for item in eligible if item[0] == winner[0]]
    if len(tied) > 1:
        raise AmbiguousRate("Multiple rates remain indistinguishable after all selection rules",
                             metadata={"candidate_ids": sorted(str(item[1].id) for item in tied),
                                       "ranking": winner[3], "rejected_candidates": rejected})
    for candidate in eligible[1:]:
        component = next(name for name, best, other in zip(RANK_COMPONENTS, winner[0], candidate[0]) if best != other)
        rejected.append({"rate_id": str(candidate[1].id), "reasons": [f"lower_{component}"], "ranking": candidate[3]})
    metadata = {"selected_rate_id": str(winner[1].id), **winner[3], "ranking_order": RANK_COMPONENTS,
                "why_it_won": "Only eligible candidate" if len(eligible) == 1 else "Highest lexicographic rank under ranking_order",
                "rejected_candidates": sorted(rejected, key=lambda value: value["rate_id"])}
    return winner[1], winner[2], metadata
