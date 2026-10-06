"""Fail-closed local demo access. This is deliberately not company authentication."""
import os
from uuid import UUID

from fastapi import HTTPException, Request


def local_demo_tenant(request: Request) -> UUID:
    if os.environ.get("CARGOAI_LOCAL_DEMO") != "1":
        raise HTTPException(403, "Pricing disabled: authenticated company access is not implemented")
    # Reject public hosts and reverse proxies, even when their peer is loopback.
    if (request.client is None or request.client.host not in {"127.0.0.1", "::1"}
            or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}
            or any(key.lower().startswith("x-forwarded-") or key.lower() == "forwarded"
                   for key in request.headers)):
        raise HTTPException(403, "Demo pricing is available only on loopback without a proxy")
    origin = request.headers.get("origin")
    if origin and origin not in {"http://localhost:3000", "http://127.0.0.1:3000"}:
        raise HTTPException(403, "Demo pricing requires a local frontend")
    try:
        return UUID(os.environ["CARGOAI_DEMO_TENANT_ID"])
    except (KeyError, ValueError):
        raise HTTPException(503, "Configure CARGOAI_DEMO_TENANT_ID from database.seed") from None


def internal_access():
    # No internal identity/role exists yet. Supplier economics must remain private.
    raise HTTPException(403, "Rate administration requires authenticated internal company access")
