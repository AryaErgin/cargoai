"""Outbound RFQ sending boundary. V1 ships only a draft-only sender: nothing is ever sent.

Approved drafts are exported as .eml (`render_eml`) and sent manually by an operator.
A real sender (SMTP / Graph / Gmail API) later implements `RFQSender` and is selected via
CARGOAI_RFQ_SENDER; until then any other value is a configuration error (fail closed).
"""
import os
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from database.repositories.supplier_repository import normalize_email
from sourcing.exceptions import SendingDisabled, SourcingConfigurationError


@dataclass(frozen=True)
class OutboundRFQ:
    """Immutable snapshot handed to a sender; it never sees the database session."""
    rfq_id: UUID
    tenant_id: UUID
    reference_code: str
    message_id: str
    from_address: str
    to_address: str
    subject: str
    body: str
    eml: bytes


@dataclass(frozen=True)
class SendResult:
    channel: str
    sent_at: datetime
    provider_message_id: str | None = None


@runtime_checkable
class RFQSender(Protocol):
    name: str

    def send(self, rfq: OutboundRFQ) -> SendResult: ...


class DraftOnlySender:
    name = "draft_only"

    def send(self, rfq: OutboundRFQ) -> SendResult:
        raise SendingDisabled("Outbound RFQ sending is disabled; export the approved draft as .eml and send it manually")


def get_sender() -> RFQSender:
    configured = os.environ.get("CARGOAI_RFQ_SENDER", "").strip().lower()
    if configured in {"", "draft_only"}:
        return DraftOnlySender()
    raise SourcingConfigurationError("Unsupported CARGOAI_RFQ_SENDER; only 'draft_only' is available")


def render_eml(rfq, from_address, *, date=None) -> bytes:
    """RFC 5322 message for manual sending. Message-ID is the stored outbound_message_id."""
    message = EmailMessage()
    message["From"] = normalize_email(from_address)
    message["To"] = normalize_email(rfq.recipient_email)
    message["Subject"] = rfq.subject
    message["Message-ID"] = rfq.outbound_message_id
    message["X-CargoAI-Reference"] = rfq.reference_code
    stamp = date or rfq.approved_at or rfq.created_at
    if stamp is not None:
        message["Date"] = format_datetime(stamp)
    message.set_content(rfq.body, charset="utf-8")
    return message.as_bytes(policy=SMTP)


def build_outbound(rfq, from_address) -> OutboundRFQ:
    return OutboundRFQ(rfq_id=rfq.id, tenant_id=rfq.tenant_id, reference_code=rfq.reference_code,
                       message_id=rfq.outbound_message_id, from_address=normalize_email(from_address),
                       to_address=rfq.recipient_email, subject=rfq.subject, body=rfq.body,
                       eml=render_eml(rfq, from_address))
