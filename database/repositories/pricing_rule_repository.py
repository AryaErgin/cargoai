from database.models import PricingRule
from database.repositories._scoped import create_owned, get_owned, list_owned


def create_pricing_rule(session, tenant_id, **values):
    """Storage only. This function does not execute or apply a rule."""
    return create_owned(session, PricingRule, tenant_id, values)


def get_pricing_rule(session, tenant_id, pricing_rule_id):
    return get_owned(session, PricingRule, tenant_id, pricing_rule_id)


def list_pricing_rules(session, tenant_id, *, limit=100, offset=0):
    return list_owned(session, PricingRule, tenant_id, limit=limit, offset=offset)
