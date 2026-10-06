from uuid import UUID

from sqlalchemy import select


def require_tenant(tenant_id):
    if not isinstance(tenant_id, UUID):
        raise ValueError("An explicit tenant UUID is required")
    return tenant_id


def scoped_statement(model, tenant_id):
    return select(model).where(model.tenant_id == require_tenant(tenant_id))


def create_owned(session, model, tenant_id, values):
    row = model(tenant_id=require_tenant(tenant_id), **values)
    session.add(row)
    session.flush()
    return row


def get_owned(session, model, tenant_id, row_id):
    return session.scalar(scoped_statement(model, tenant_id).where(model.id == row_id))


def list_owned(session, model, tenant_id, *, limit=100, offset=0):
    if not 1 <= limit <= 1000 or offset < 0:
        raise ValueError("limit must be 1..1000 and offset nonnegative")
    return list(session.scalars(scoped_statement(model, tenant_id).order_by(model.id).limit(limit).offset(offset)))
