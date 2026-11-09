"""Environment configuration for carrier sourcing; invalid values fail closed."""
import os
import re

from sourcing.exceptions import SourcingConfigurationError

DEFAULT_MAX_CARRIERS = 5
DEFAULT_RESPONSE_HOURS = 48
DEFAULT_MESSAGE_DOMAIN = "cargoai.invalid"
_DOMAIN = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")


def _bounded_int(name, default, minimum, maximum):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    if not raw.isdigit() or not minimum <= int(raw) <= maximum:
        raise SourcingConfigurationError(f"{name} must be a whole number between {minimum} and {maximum}")
    return int(raw)


def max_carriers():
    return _bounded_int("CARGOAI_RFQ_MAX_CARRIERS", DEFAULT_MAX_CARRIERS, 1, 20)


def response_hours():
    return _bounded_int("CARGOAI_RFQ_RESPONSE_HOURS", DEFAULT_RESPONSE_HOURS, 1, 720)


def message_domain():
    domain = os.environ.get("CARGOAI_RFQ_MESSAGE_DOMAIN", "").strip().lower() or DEFAULT_MESSAGE_DOMAIN
    if not _DOMAIN.match(domain):
        raise SourcingConfigurationError("CARGOAI_RFQ_MESSAGE_DOMAIN must be a plain DNS domain")
    return domain
