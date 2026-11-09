"""RFQ reference codes and outbound Message-IDs (random, never derived from business data)."""
import re
import secrets
from uuid import uuid4

from database.repositories.sourcing_repository import reference_code_exists
from sourcing.config import message_domain
from sourcing.exceptions import SourcingConflict

# Crockford base32: no I, L, O, U.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PREFIX = "CAI-RFQ-"
REFERENCE_PATTERN = re.compile(r"CAI-RFQ-[0-9A-HJKMNP-TV-Z]{8}")
MAX_ATTEMPTS = 8


def generate_reference_code():
    return PREFIX + "".join(secrets.choice(ALPHABET) for _ in range(8))


def new_reference_code(session, tenant_id, *, generator=None, taken=()):
    """Unique per tenant; `taken` covers codes allocated in this unit of work but not yet flushed."""
    generator = generator or generate_reference_code
    for _ in range(MAX_ATTEMPTS):
        code = generator()
        if not REFERENCE_PATTERN.fullmatch(code):
            raise ValueError("Reference generator produced an invalid code")
        if code not in taken and not reference_code_exists(session, tenant_id, code):
            return code
    raise SourcingConflict("Could not allocate a unique RFQ reference code; retry")


def new_outbound_message_id(domain=None):
    return f"<rfq.{uuid4()}@{domain or message_domain()}>"
