class RateManagementError(Exception):
    def __init__(self, message, *, code="INVALID_RATE", http_status=422, metadata=None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.metadata = metadata or {}


class NotFound(RateManagementError):
    def __init__(self):
        super().__init__("Resource not found for this tenant", code="NOT_FOUND", http_status=404)


class Conflict(RateManagementError):
    def __init__(self, message, *, code="CONFLICT", metadata=None):
        super().__init__(message, code=code, http_status=409, metadata=metadata)
