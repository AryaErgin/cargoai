"""Tenant-scoped carrier (supplier) contacts and lane capabilities."""

from database.models import Supplier, SupplierContact, SupplierLaneCapability
from database.repositories._scoped import create_owned, get_owned, list_owned, require_tenant, scoped_statement

RFQ_SUPPLIER_TYPES = ("OCEAN_CARRIER", "NVOCC", "OVERSEAS_AGENT")


def normalize_email(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Contact email must not be empty")
    email = value.strip().lower()
    if any(character.isspace() or ord(character) < 32 for character in email) or email.count("@") != 1:
        raise ValueError("Contact email must be a single plain address")
    local, domain = email.split("@")
    if not local or "." not in domain or len(email) > 320:
        raise ValueError("Contact email must be a single plain address")
    return email


def create_supplier(session, tenant_id, **values):
    return create_owned(session, Supplier, tenant_id, values)


def get_supplier(session, tenant_id, supplier_id):
    return get_owned(session, Supplier, tenant_id, supplier_id)


def find_supplier_by_name(session, tenant_id, name):
    return session.scalar(scoped_statement(Supplier, tenant_id).where(Supplier.name == name).order_by(Supplier.id))


def list_suppliers(session, tenant_id, *, limit=100, offset=0):
    return list_owned(session, Supplier, tenant_id, limit=limit, offset=offset)


def list_rfq_suppliers(session, tenant_id):
    """Active suppliers of a type that may receive ocean-FCL RFQs."""
    return list(session.scalars(scoped_statement(Supplier, tenant_id).where(
        Supplier.is_active.is_(True), Supplier.supplier_type.in_(RFQ_SUPPLIER_TYPES)).order_by(Supplier.id)))


def create_supplier_contact(session, tenant_id, **values):
    values["email"] = normalize_email(values.get("email"))
    return create_owned(session, SupplierContact, tenant_id, values)


def get_supplier_contact(session, tenant_id, contact_id):
    return get_owned(session, SupplierContact, tenant_id, contact_id)


def find_supplier_contact(session, tenant_id, supplier_id, email):
    return session.scalar(scoped_statement(SupplierContact, tenant_id).where(
        SupplierContact.supplier_id == supplier_id, SupplierContact.email == normalize_email(email)))


def list_supplier_contacts(session, tenant_id, *, supplier_id=None):
    query = scoped_statement(SupplierContact, tenant_id)
    if supplier_id is not None:
        query = query.where(SupplierContact.supplier_id == supplier_id)
    return list(session.scalars(query.order_by(SupplierContact.email, SupplierContact.id)))


def list_rfq_contacts(session, tenant_id, supplier_ids):
    """Active RFQ recipients for the given suppliers, ordered by email then id (deterministic)."""
    require_tenant(tenant_id)
    if not supplier_ids:
        return []
    return list(session.scalars(scoped_statement(SupplierContact, tenant_id).where(
        SupplierContact.supplier_id.in_(list(supplier_ids)), SupplierContact.is_active.is_(True),
        SupplierContact.is_rfq_recipient.is_(True)).order_by(SupplierContact.email, SupplierContact.id)))


def create_lane_capability(session, tenant_id, **values):
    for side in ("origin", "destination"):
        key = f"{side}_country_code"
        if values.get(key) is not None:
            values[key] = values[key].strip().upper()
    return create_owned(session, SupplierLaneCapability, tenant_id, values)


def get_lane_capability(session, tenant_id, capability_id):
    return get_owned(session, SupplierLaneCapability, tenant_id, capability_id)


def list_lane_capabilities(session, tenant_id, *, supplier_id=None, mode=None, active_only=False):
    query = scoped_statement(SupplierLaneCapability, tenant_id)
    if supplier_id is not None:
        query = query.where(SupplierLaneCapability.supplier_id == supplier_id)
    if mode is not None:
        query = query.where(SupplierLaneCapability.mode == mode)
    if active_only:
        query = query.where(SupplierLaneCapability.is_active.is_(True))
    return list(session.scalars(query.order_by(SupplierLaneCapability.id)))
