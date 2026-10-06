from datetime import date
from decimal import Decimal

from sqlalchemy import or_

from database.models import ExchangeRate
from database.repositories._scoped import create_owned, scoped_statement


def create_exchange_rate(session, tenant_id, *, base_currency, quote_currency, rate,
                         effective_from, effective_to=None, source=None):
    if not isinstance(rate, Decimal) or not rate.is_finite() or rate <= 0:
        raise ValueError("FX rate must be a positive finite Decimal")
    if len(base_currency) != 3 or len(quote_currency) != 3:
        raise ValueError("FX currencies must be three-letter codes")
    return create_owned(session, ExchangeRate, tenant_id, {
        "base_currency": base_currency.upper(), "quote_currency": quote_currency.upper(),
        "rate": rate, "effective_from": effective_from, "effective_to": effective_to, "source": source})


def find_exchange_rates(session, tenant_id, base_currency, quote_currency, effective_date):
    if not isinstance(effective_date, date):
        raise ValueError("effective_date must be a date")
    return list(session.scalars(scoped_statement(ExchangeRate, tenant_id).where(
        ExchangeRate.base_currency == base_currency.upper(), ExchangeRate.quote_currency == quote_currency.upper(),
        ExchangeRate.effective_from <= effective_date,
        or_(ExchangeRate.effective_to.is_(None), ExchangeRate.effective_to >= effective_date),
    ).order_by(ExchangeRate.effective_from, ExchangeRate.id)))
