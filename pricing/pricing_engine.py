from decimal import Decimal, localcontext

from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import ValidationError

from database.models import Tenant, Customer, Location, EquipmentType, Quote, QuoteLine
from pricing.charge_calculator import calculate_charges
from pricing.exceptions import (PricingError, InvalidPricingRequest, NoRateFound, MissingFX,
                                AmbiguousRate, AmbiguousPricingRule)
from pricing.fx_service import FXService
from pricing.models import PricingRequest, QuoteResult
from pricing.money import ZERO, HUNDRED, PRECISION, money
from pricing.rate_selector import select_rate
from pricing.rule_selector import select_rules


def _validate_context(session, request):
    tenant = session.get(Tenant, request.tenant_id)
    if tenant is None or not tenant.is_active:
        raise InvalidPricingRequest("Tenant is unknown or inactive")
    if request.customer_id is not None:
        customer = session.scalar(select(Customer).where(Customer.tenant_id == request.tenant_id,
                                                        Customer.id == request.customer_id, Customer.is_active.is_(True)))
        if customer is None:
            raise InvalidPricingRequest("Customer is unknown or inactive for this tenant")
    origin = session.get(Location, request.origin_location_id)
    destination = session.get(Location, request.destination_location_id)
    equipment = session.get(EquipmentType, request.equipment_type_id)
    if origin is None or destination is None:
        raise InvalidPricingRequest("Origin and destination must resolve to known locations")
    if (equipment is None or not equipment.supported or equipment.transport_mode != "OCEAN"
            or equipment.canonical_code not in {"20GP", "40GP", "40HC"}):
        raise InvalidPricingRequest("V1 supports only 20GP, 40GP and 40HC equipment")
    if request.dangerous_goods is True:
        raise InvalidPricingRequest("V1 cannot price dangerous goods: stored rates have no DG qualification")
    return origin, destination, equipment


def _execute_rules(session, request, buy, fx):
    markup, margin, discount = ZERO, ZERO, ZERO
    applied = []
    for slot, rule, selection in select_rules(session, request):
        if not isinstance(rule.value, Decimal) or not rule.value.is_finite() or rule.value < ZERO:
            raise PricingError("Pricing rule value must be finite and nonnegative")
        conversion = None
        if rule.rule_type in {"PERCENT_MARKUP", "DISCOUNT"}:
            if rule.currency is not None:
                raise PricingError("Percentage markup/discount rules must not specify a currency")
            if rule.rule_type == "DISCOUNT" and rule.value > HUNDRED:
                raise PricingError("Percentage discount cannot exceed 100")
        else:
            if not rule.currency:
                raise PricingError("Fixed markup/minimum-margin rules require an explicit currency")
            conversion = fx.lookup(rule.currency)
        if slot == "markup":
            markup = buy * rule.value / HUNDRED if rule.rule_type == "PERCENT_MARKUP" else fx.convert(rule.value, rule.currency)
            margin = markup
            amount = markup
        elif slot == "minimum_margin":
            minimum = fx.convert(rule.value, rule.currency)
            amount = max(ZERO, minimum - margin)
            margin = max(margin, minimum)
        else:
            discount = (buy + margin) * rule.value / HUNDRED
            amount = discount
        applied.append({"rule_id": str(rule.id), "name": rule.name, "rule_type": rule.rule_type,
            "slot": slot, "source_value": str(rule.value), "source_currency": rule.currency,
            "value_basis": "PERCENTAGE" if rule.rule_type in {"PERCENT_MARKUP", "DISCOUNT"} else "FIXED_AMOUNT",
            "applied_amount": str(money(amount)), "calculation_amount": str(amount),
            "fx_rate_id": str(conversion["rate_id"]) if conversion and conversion["rate_id"] else None,
            "fx_rate_value": str(conversion["rate"]) if conversion else None, **selection})
    sell = money(buy + margin - discount)
    final_margin = money(sell - buy)
    return markup, discount, sell, final_margin, applied


def _persist(session, request, result):
    with session.begin_nested():
        quote = Quote(tenant_id=request.tenant_id, customer_id=request.customer_id,
            currency=result.currency, buy_total=result.buy_total, sell_total=result.sell_total,
            margin_amount=result.final_margin_amount, margin_percent=result.margin_percent, status="DRAFT")
        session.add(quote)
        session.flush()
        result.quote_id = quote.id
        quote.calculation_json = {"engine_version": "ocean_fcl_v1", "request": request.model_dump(mode="json"),
                                  "result": result.model_dump(mode="json")}
        for line in result.line_items:
            session.add(QuoteLine(tenant_id=request.tenant_id, quote_id=quote.id, rate_id=result.selected_rate_id,
                rate_charge_id=line.rate_charge_id, description=line.charge_type, quantity=line.quantity,
                unit_amount=line.converted_unit_amount, total_amount=line.converted_total,
                currency=result.currency, basis=line.basis, calculation_json=line.model_dump(mode="json")))
        session.flush()


def price_quote(session: Session, request: PricingRequest, *, persist: bool = False) -> QuoteResult:
    """Price a validated PricingRequest. Caller owns commit/rollback.

    Expected selection/FX failures are domain results. Invalid requests or unsafe
    charge/rule configuration raise PricingError without creating a quote.
    """
    if not isinstance(request, PricingRequest):
        raise InvalidPricingRequest("Pricing requires a structured PricingRequest")
    try:
        # Revalidate copied models too; Pydantic model_copy(update=...) skips validation.
        request = PricingRequest.model_validate(request.model_dump())
    except ValidationError:
        raise InvalidPricingRequest("Invalid structured pricing request") from None
    origin, destination, equipment = _validate_context(session, request)
    result = QuoteResult(tenant_id=request.tenant_id, customer_id=request.customer_id,
        equipment=equipment.canonical_code, container_count=request.container_count, origin=origin.name,
        destination=destination.name, effective_date=request.effective_date, currency=request.requested_currency,
        status="NO_RATE_FOUND")
    fx = FXService(session, request.tenant_id, request.effective_date, request.requested_currency)
    try:
        with localcontext() as context:
            context.prec = PRECISION
            rate, sheet, metadata = select_rate(session, request)
            result.selected_rate_id = rate.id
            result.supplier_id = rate.supplier_id if rate.supplier_id is not None else sheet.supplier_id
            result.rate_selection_metadata = metadata
            lines, optional = calculate_charges(session, request, rate, fx)
            buy = money(sum((line.converted_total for line in lines), ZERO))
            markup, discount, sell, margin, applied = _execute_rules(session, request, buy, fx)
            result.line_items = lines
            result.optional_charges_available = optional
            result.buy_total = buy
            result.markup_amount = money(markup)
            result.discount_amount = money(discount)
            result.sell_total = sell
            result.final_margin_amount = margin
            result.margin_percent = money(margin / sell * HUNDRED) if sell else None
            result.applied_pricing_rules = applied
            result.fx_conversions = fx.metadata()
            result.status = "PRICED"
    except (NoRateFound, MissingFX, AmbiguousRate, AmbiguousPricingRule) as error:
        result.status = error.code
        result.error = str(error)
        result.error_metadata = error.metadata
        result.fx_conversions = fx.metadata()
        if isinstance(error, (NoRateFound, AmbiguousRate)):
            result.rate_selection_metadata = error.metadata
        return result
    if persist:
        _persist(session, request, result)
    return result
