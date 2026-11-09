class SourcingError(Exception):
    code = "INVALID_SOURCING_REQUEST"
    http_status = 422

    def __init__(self, message, *, metadata=None):
        super().__init__(message)
        self.metadata = metadata or {}


class InvalidSourcingRequest(SourcingError):
    code = "INVALID_REQUEST"


class SourcingNotFound(SourcingError):
    code = "NOT_FOUND"
    http_status = 404

    def __init__(self, message="Resource not found for this tenant", *, metadata=None):
        super().__init__(message, metadata=metadata)


class RateAvailable(SourcingError):
    """Re-pricing found a usable rate (or only FX/rule configuration is missing); sourcing is not needed."""
    code = "RATE_AVAILABLE"
    http_status = 409


class AmbiguousRate(SourcingError):
    code = "AMBIGUOUS_RATE"
    http_status = 409


class InvalidTransition(SourcingError):
    code = "INVALID_TRANSITION"
    http_status = 409


class SourcingConflict(SourcingError):
    code = "CONFLICT"
    http_status = 409


class ReferenceCodeRequired(SourcingError):
    code = "REFERENCE_CODE_REQUIRED"


class SendingDisabled(SourcingError):
    code = "SENDING_DISABLED"
    http_status = 409


class SourcingConfigurationError(SourcingError):
    code = "SOURCING_CONFIGURATION"
    http_status = 503
