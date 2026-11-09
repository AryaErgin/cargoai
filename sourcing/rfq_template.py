"""Deterministic English RFQ template (no LLM). Bump TEMPLATE_VERSION on any wording change.

Only the shipment facts the user approved for carriers are accepted (Q5): POL/POD, equipment type and
count, general commodity, gross weight, cargo-ready date, incoterm and DG status. The context type has
no field for customer identity, sell/target price, other carriers or rate history, so they cannot leak.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

TEMPLATE_VERSION = "rfq_ocean_fcl_en_v2"
NOT_SPECIFIED = "Not specified"
# Optional cargo facts the customer may not know yet; the draft is still created (v2).
TO_BE_ADVISED = "To be advised"


@dataclass(frozen=True)
class RFQContext:
    reference_code: str
    origin_name: str
    origin_locode: str | None
    destination_name: str
    destination_locode: str | None
    equipment_code: str
    container_count: int
    cargo_ready_date: date
    dangerous_goods: bool
    response_due_at: datetime
    forwarder_name: str
    incoterm: str | None = None
    commodity: str | None = None
    gross_weight_kg: Decimal | None = None


def single_line(value):
    """Collapse whitespace/control characters so free text cannot inject headers or fake sections."""
    if value is None:
        return None
    text = " ".join("".join(ch if ch.isprintable() else " " for ch in str(value)).split())
    return text or None


def _place(name, locode):
    name = single_line(name)
    return f"{name} ({locode})" if locode else name


def format_weight(value):
    """Fixed format: comma thousands separator, no trailing zeros, e.g. 18,500 kg / 18,500.25 kg."""
    if value is None:
        return TO_BE_ADVISED
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError("Gross weight must be a positive finite Decimal")
    return f"{format(value.normalize(), ',f')} kg"


def marker(reference_code):
    return f"--- CargoAI reference: {reference_code} (please keep in reply) ---"


def render_rfq(context: RFQContext) -> tuple[str, str]:
    if context.dangerous_goods is not False:
        raise ValueError("Dangerous-goods shipments are not sourced in V1")
    if context.response_due_at.tzinfo is None:
        raise ValueError("response_due_at must be timezone-aware")
    origin = _place(context.origin_name, context.origin_locode)
    destination = _place(context.destination_name, context.destination_locode)
    equipment = f"{context.container_count} x {single_line(context.equipment_code)}"
    due = context.response_due_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = f"RFQ {context.reference_code} | Ocean FCL | {origin} -> {destination} | {equipment}"
    body = "\n".join([
        "Dear partner,",
        "",
        "Please quote your best ocean FCL rate for the shipment below.",
        "",
        f"Reference: {context.reference_code}",
        f"Port of loading (POL): {origin}",
        f"Port of discharge (POD): {destination}",
        f"Equipment: {equipment}",
        f"Commodity: {single_line(context.commodity) or TO_BE_ADVISED}",
        f"Gross weight: {format_weight(context.gross_weight_kg)}",
        f"Cargo ready date: {context.cargo_ready_date.isoformat()}",
        f"Incoterm: {single_line(context.incoterm) or NOT_SPECIFIED}",
        "Dangerous goods: No",
        "",
        f"Please reply by {due} and state in your reply:",
        "- Ocean freight per container",
        "- Surcharges (e.g. BAF, GRI) and their basis",
        "- Origin and destination local charges",
        "- Currency",
        "- Rate validity (from / to)",
        "- Transit time",
        "- Free time",
        "",
        "Please keep the reference code in the subject of your reply.",
        "",
        "Kind regards,",
        single_line(context.forwarder_name) or "CargoAI",
        "",
        marker(context.reference_code),
    ]) + "\n"
    return subject, body
