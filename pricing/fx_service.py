from decimal import Decimal, localcontext

from database.repositories.exchange_rate_repository import find_exchange_rates
from pricing.exceptions import MissingFX, PricingError
from pricing.money import ONE, PRECISION


class FXService:
    def __init__(self, session, tenant_id, effective_date, quote_currency):
        self.session = session
        self.tenant_id = tenant_id
        self.effective_date = effective_date
        self.quote_currency = quote_currency
        self._cache = {}

    def lookup(self, source_currency):
        source_currency = source_currency.upper()
        if source_currency not in self._cache:
            if source_currency == self.quote_currency:
                value = {"base_currency": source_currency, "quote_currency": self.quote_currency,
                         "rate_id": None, "rate": ONE, "source": "same_currency", "effective_date": self.effective_date.isoformat()}
            else:
                rows = find_exchange_rates(self.session, self.tenant_id, source_currency, self.quote_currency, self.effective_date)
                if len(rows) != 1:
                    raise MissingFX(f"Expected one valid {source_currency} → {self.quote_currency} FX rate on {self.effective_date}; found {len(rows)}",
                                    metadata={"base_currency": source_currency, "quote_currency": self.quote_currency,
                                              "matched_fx_ids": [str(row.id) for row in rows]})
                row = rows[0]
                if not isinstance(row.rate, Decimal) or not row.rate.is_finite() or row.rate <= 0:
                    raise PricingError("Stored FX rate must be positive and finite")
                value = {"base_currency": source_currency, "quote_currency": self.quote_currency,
                         "rate_id": row.id, "rate": row.rate, "source": row.source,
                         "effective_from": row.effective_from.isoformat(),
                         "effective_to": row.effective_to.isoformat() if row.effective_to else None,
                         "effective_date": self.effective_date.isoformat()}
            self._cache[source_currency] = value
        return self._cache[source_currency]

    def convert(self, amount, source_currency):
        if not isinstance(amount, Decimal):
            raise PricingError("Monetary amounts must be Decimal")
        with localcontext() as context:
            context.prec = PRECISION
            return amount * self.lookup(source_currency)["rate"]

    def metadata(self):
        return [self._cache[currency] for currency in sorted(self._cache)]
