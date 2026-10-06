from decimal import Decimal, localcontext

from sqlalchemy import select

from database.models import RateCharge, ChargeType
from pricing.exceptions import PricingError
from pricing.matching import applicable_dates
from pricing.models import QuoteLineResult
from pricing.money import ZERO, ONE, HUNDRED, PRECISION, money

SUPPORTED_BASES = {"PER_CONTAINER", "PER_SHIPMENT", "FLAT", "PERCENTAGE"}


def _bounded(total, charge):
    if charge.minimum_amount is not None:
        total = max(total, charge.minimum_amount)
    if charge.maximum_amount is not None:
        total = min(total, charge.maximum_amount)
    return total


def _line(charge, charge_type, quantity, source_total, fx, *, percentage_subtotal=None):
    conversion = fx.lookup(charge.currency)
    raw_total = source_total * conversion["rate"]
    raw_unit = raw_total / quantity
    return QuoteLineResult(rate_charge_id=charge.id, charge_type=charge_type.canonical_code,
        category=charge_type.category, source_amount=charge.amount, source_currency=charge.currency,
        source_total_amount=source_total, quantity=quantity, basis=charge.basis,
        percentage_base=charge.percentage_base, percentage_base_subtotal=percentage_subtotal,
        converted_unit_amount=money(raw_unit), converted_total=money(raw_total),
        calculation_unit_amount=raw_unit, calculation_total=raw_total, quote_currency=fx.quote_currency,
        fx_rate_id=conversion["rate_id"], fx_rate_value=conversion["rate"])


def calculate_charges(session, request, rate, fx):
    rows = list(session.execute(select(RateCharge, ChargeType).join(ChargeType,
        ChargeType.id == RateCharge.charge_type_id).where(RateCharge.tenant_id == request.tenant_id,
        RateCharge.rate_id == rate.id).order_by(RateCharge.id)))
    regular, percentages, optional = [], [], []
    for charge, charge_type in rows:
        if not applicable_dates(charge, request.effective_date):
            continue
        if charge.equipment_type_id is not None and charge.equipment_type_id != request.equipment_type_id:
            continue
        if not charge.mandatory:
            optional.append({"rate_charge_id": str(charge.id), "charge_type": charge_type.canonical_code,
                             "amount": str(charge.amount), "currency": charge.currency, "basis": charge.basis,
                             "percentage_base": charge.percentage_base})
            continue
        if charge.basis not in SUPPORTED_BASES:
            raise PricingError(f"Unsupported mandatory charge basis: {charge.basis}")
        if not isinstance(charge.amount, Decimal) or not charge.amount.is_finite() or charge.amount < ZERO:
            raise PricingError("Mandatory charge amount must be finite and nonnegative")
        for bound in (charge.minimum_amount, charge.maximum_amount):
            if bound is not None and (not isinstance(bound, Decimal) or not bound.is_finite() or bound < ZERO):
                raise PricingError("Charge bounds must be finite nonnegative Decimal amounts")
        (percentages if charge.basis == "PERCENTAGE" else regular).append((charge, charge_type))
    if not regular and not percentages:
        raise PricingError("Selected rate has no applicable mandatory charges")
    lines = []
    with localcontext() as context:
        context.prec = PRECISION
        for charge, charge_type in regular:
            quantity = Decimal(request.container_count) if charge.basis == "PER_CONTAINER" else ONE
            source_total = _bounded(charge.amount * quantity, charge)
            lines.append(_line(charge, charge_type, quantity, source_total, fx))
        buy_subtotal = sum((line.calculation_total for line in lines), ZERO)
        freight_subtotal = sum((line.calculation_total for line in lines if line.category == "FREIGHT"), ZERO)
        for charge, charge_type in percentages:
            if charge.percentage_base not in {"FREIGHT_SUBTOTAL", "BUY_SUBTOTAL"}:
                raise PricingError("PERCENTAGE charge requires explicit FREIGHT_SUBTOTAL or BUY_SUBTOTAL")
            base = freight_subtotal if charge.percentage_base == "FREIGHT_SUBTOTAL" else buy_subtotal
            conversion = fx.lookup(charge.currency)
            source_total = _bounded((base / conversion["rate"]) * charge.amount / HUNDRED, charge)
            lines.append(_line(charge, charge_type, ONE, source_total, fx, percentage_subtotal=base))
        return sorted(lines, key=lambda line: str(line.rate_charge_id)), optional
