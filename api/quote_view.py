"""Customer presentation of the engine result; never expose supplier economics."""
from decimal import Decimal, localcontext

from database.models import Rate, RateSheet
from pricing.money import money, PRECISION


def customer_quote(session, result):
    rate = session.get(Rate, result.selected_rate_id)
    sheet = session.get(RateSheet, rate.rate_sheet_id)
    # Allocate the engine's final sell total proportionally for display only.
    # Last line absorbs rounding so displayed charges sum to the engine total.
    charges, allocated = [], Decimal("0")
    with localcontext() as context:
        context.prec = PRECISION
        for index, line in enumerate(result.line_items):
            amount = (result.sell_total - allocated if index == len(result.line_items) - 1 else
                      money(result.sell_total * line.converted_total / result.buy_total)
                      if result.buy_total else Decimal("0.00"))
            allocated += amount
            charges.append({"description": line.charge_type, "basis": line.basis,
                            "quantity": str(line.quantity), "sell_amount": str(amount)})
    starts = [value for value in (rate.valid_from, sheet.valid_from) if value]
    ends = [value for value in (rate.valid_to, sheet.valid_to) if value]
    return {"status": result.status, "quote_id": str(result.quote_id) if result.quote_id else None,
            "shipment": {"origin": result.origin, "destination": result.destination,
                         "equipment": result.equipment, "container_count": result.container_count,
                         "effective_date": result.effective_date.isoformat()},
            "currency": result.currency, "sell_total": str(result.sell_total), "charges": charges,
            "charge_presentation": "Final sell total allocated proportionally across included charges",
            "selected_rate_id": str(rate.id), "rate_reference": rate.source_reference or str(rate.id),
            "valid_from": max(starts).isoformat() if starts else None,
            "valid_to": min(ends).isoformat() if ends else None,
            "demo_data": True}
