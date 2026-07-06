"""Per-merchant admin / ops endpoints.

config-status   — which fiscal fields + credential refs are set, and the chain head
test-login      — authenticate against MoR (no invoice sent) — the auth smoke test
reconciliation  — verify locally-Registered docs against MoR (read-only)
retry           — re-register Failed documents

These are operator tools; in production gate them behind admin auth (out of scope
for the sandbox stage).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import mor_client, registration
from app.db import get_session
from app.models import InvoiceChain, Merchant
from app.secrets_backend import get_secrets_backend

router = APIRouter(prefix="/admin/{tin}", tags=["admin"])


def _merchant(session: Session, tin: str) -> Merchant:
    try:
        return registration.get_merchant_by_tin(session, tin)
    except registration.MerchantNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/config-status")
def config_status(tin: str, session: Session = Depends(get_session)) -> dict:
    """Show which config/credentials are present (booleans only — no secrets) and
    the current invoice-chain head."""
    merchant = _merchant(session, tin)
    secret = getattr(merchant, "secret", None)
    chain = session.get(InvoiceChain, merchant.id)
    return {
        "tin": merchant.tin,
        "legal_name": merchant.legal_name,
        "system_type": merchant.system_type,
        "system_number": merchant.system_number,
        "base_url": merchant.base_url,
        "tax_code": merchant.tax_code,
        "vat_number_set": bool(merchant.vat_number),
        "tls_verify": merchant.tls_verify,
        "default_buyer_id_set": bool(merchant.default_buyer_id_type and merchant.default_buyer_id_number),
        "secrets": {
            "client_id_set": bool(secret and secret.client_id),
            "client_secret_ref_set": bool(secret and secret.client_secret),
            "api_key_ref_set": bool(secret and secret.api_key),
            "private_key_ref_set": bool(secret and secret.private_key_ref),
            "certificate_ref_set": bool(secret and secret.certificate_ref),
        },
        "chain": {
            "counter": int(chain.counter) if chain else 0,
            "last_irn": chain.last_irn if chain else None,
        },
    }


@router.post("/test-login")
def test_login(tin: str, session: Session = Depends(get_session)) -> dict:
    """Authenticate against MoR /auth/login (no invoice). The auth smoke test."""
    merchant = _merchant(session, tin)
    secrets = get_secrets_backend().load_merchant_credentials(merchant)
    try:
        token = mor_client.login(merchant, secrets)
        return {"ok": True, "token_prefix": (token or "")[:12]}
    except Exception as exc:  # MorAuthError, missing secret, transport, etc.
        return {"ok": False, "error": str(exc)}


@router.get("/reconciliation")
def reconcile(tin: str, limit: int = 50, session: Session = Depends(get_session)) -> dict:
    """Verify up to ``limit`` locally-Registered documents against MoR (read-only)."""
    merchant = _merchant(session, tin)
    return registration.reconciliation(session, limit=limit, merchant=merchant)


@router.post("/retry")
def retry(tin: str, limit: int = 50, session: Session = Depends(get_session)) -> dict:
    """Re-register up to ``limit`` Failed documents for this merchant."""
    merchant = _merchant(session, tin)
    return registration.retry_failed(session, limit=limit, merchant=merchant)
