class PricingError(Exception):
    code = "INVALID_CONFIGURATION"
    http_status = 422

    def __init__(self, message, *, metadata=None):
        super().__init__(message)
        self.metadata = metadata or {}


class InvalidPricingRequest(PricingError):
    code = "INVALID_REQUEST"


class NoRateFound(PricingError):
    code = "NO_RATE_FOUND"


class MissingFX(PricingError):
    code = "MISSING_FX"


class AmbiguousRate(PricingError):
    code = "AMBIGUOUS_RATE"
    http_status = 409


class AmbiguousPricingRule(PricingError):
    code = "AMBIGUOUS_PRICING_RULE"
    http_status = 409


class AmbiguousReference(PricingError):
    code = "AMBIGUOUS_REFERENCE"
    http_status = 409
