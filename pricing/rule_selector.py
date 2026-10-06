from sqlalchemy import select

from database.models import PricingRule
from pricing.exceptions import AmbiguousPricingRule, PricingError
from pricing.matching import applicable_dates, location_groups, matches_target

SUPPORTED_RULES = {"PERCENT_MARKUP", "FIXED_MARKUP", "MINIMUM_MARGIN", "DISCOUNT"}


def _specificity(rule):
    customer = rule.customer_id is not None
    lane = any(value is not None for value in (rule.origin_location_id, rule.origin_group_id,
                                               rule.destination_location_id, rule.destination_group_id))
    equipment = rule.equipment_type_id is not None
    return (1 if lane and equipment else 2 if lane else 3 if equipment else 4) + (0 if customer else 4)


def select_rules(session, request):
    origins = location_groups(session, request.tenant_id, request.origin_location_id)
    destinations = location_groups(session, request.tenant_id, request.destination_location_id)
    applicable = []
    for rule in session.scalars(select(PricingRule).where(PricingRule.tenant_id == request.tenant_id,
                                                        PricingRule.is_active.is_(True))):
        if not applicable_dates(rule, request.effective_date):
            continue
        if rule.mode is not None and rule.mode != request.mode:
            continue
        if rule.customer_id is not None and rule.customer_id != request.customer_id:
            continue
        if rule.equipment_type_id is not None and rule.equipment_type_id != request.equipment_type_id:
            continue
        if not matches_target(rule.origin_location_id, rule.origin_group_id, request.origin_location_id, origins):
            continue
        if not matches_target(rule.destination_location_id, rule.destination_group_id, request.destination_location_id, destinations):
            continue
        if rule.rule_type not in SUPPORTED_RULES:
            raise PricingError(f"Unsupported applicable pricing rule: {rule.rule_type}")
        applicable.append(rule)
    selected = []
    for slot, types in (("markup", {"PERCENT_MARKUP", "FIXED_MARKUP"}),
                        ("minimum_margin", {"MINIMUM_MARGIN"}), ("discount", {"DISCOUNT"})):
        candidates = [rule for rule in applicable if rule.rule_type in types]
        if not candidates:
            continue
        rank = lambda rule: (-_specificity(rule), rule.priority)
        best = max(rank(rule) for rule in candidates)
        tied = [rule for rule in candidates if rank(rule) == best]
        if len(tied) != 1:
            raise AmbiguousPricingRule(f"Competing {slot} rules have equal specificity and priority",
                metadata={"slot": slot, "candidate_ids": sorted(str(rule.id) for rule in tied)})
        winner = tied[0]
        selected.append((slot, winner, {"specificity_level": _specificity(winner), "priority": winner.priority,
            "rejected_rule_ids": sorted(str(rule.id) for rule in candidates if rule.id != winner.id)}))
    return selected
