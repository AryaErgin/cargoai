from database.models import Customer
from database.repositories._scoped import create_owned, get_owned, list_owned


def create_customer(session, tenant_id, **values):
    return create_owned(session, Customer, tenant_id, values)


def get_customer(session, tenant_id, customer_id):
    return get_owned(session, Customer, tenant_id, customer_id)


def list_customers(session, tenant_id, *, limit=100, offset=0):
    return list_owned(session, Customer, tenant_id, limit=limit, offset=offset)
