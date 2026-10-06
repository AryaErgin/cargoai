from decimal import Decimal, ROUND_HALF_UP, localcontext

PRECISION = 38
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Money must be a finite Decimal")
    with localcontext() as context:
        context.prec = PRECISION
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
