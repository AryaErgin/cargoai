from sqlalchemy import Enum


def enumeration(name, *values):
    # Portable checked VARCHAR rather than PostgreSQL-only enum lifecycle.
    return Enum(*values, name=name, native_enum=False, create_constraint=True, validate_strings=True)


LOCATION_TYPE = enumeration("location_type", "PORT", "AIRPORT", "CITY", "WAREHOUSE", "REGION", "OTHER")
TRANSPORT_MODE = enumeration("transport_mode", "OCEAN", "ROAD", "AIR", "OTHER")
RATE_MODE = enumeration("rate_mode", "OCEAN_FCL", "OCEAN_LCL", "AIR", "ROAD_FTL", "ROAD_LTL", "OTHER")
SOURCE_TYPE = enumeration("source_type", "MANUAL", "EXCEL", "CSV", "PDF", "EMAIL", "API", "OTHER")
SUPPLIER_TYPE = enumeration("supplier_type", "OCEAN_CARRIER", "AIRLINE", "TRUCKER", "OVERSEAS_AGENT", "NVOCC", "OTHER")
SHEET_STATUS = enumeration("sheet_status", "DRAFT", "ACTIVE", "EXPIRED", "ARCHIVED")
CHARGE_CATEGORY = enumeration("charge_category", "FREIGHT", "ORIGIN", "DESTINATION", "DOCUMENTATION", "SECURITY", "SURCHARGE", "INLAND", "CUSTOMS", "OTHER")
CHARGE_BASIS = enumeration("charge_basis", "PER_CONTAINER", "PER_SHIPMENT", "PER_BILL", "PER_KG", "PER_CHARGEABLE_KG", "PER_CBM", "PER_PALLET", "PER_TRIP", "PER_KM", "PER_MONTH", "PERCENTAGE", "FLAT")
RULE_TYPE = enumeration("rule_type", "PERCENT_MARKUP", "FIXED_MARKUP", "MINIMUM_MARGIN", "CHARGE_OVERRIDE", "DISCOUNT", "OTHER")
IMPORT_STATUS = enumeration("import_status", "PENDING", "PROCESSING", "REVIEW_REQUIRED", "COMPLETED", "FAILED")
QUOTE_STATUS = enumeration("quote_status", "DRAFT", "REVIEW", "APPROVED", "SENT", "EXPIRED")
SUPPLIER_COMMERCIAL_TYPE = enumeration("supplier_commercial_type", "SPOT", "CONTRACT")
COMMERCIAL_TYPE = enumeration("commercial_type", "SPOT", "CONTRACT", "CUSTOMER_FIXED")
