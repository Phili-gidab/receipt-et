"""End-to-end MoR sandbox smoke test for the Delta merchant.

THE deliverable that proves the platform works against the real sandbox once
Delta's credentials are dropped in. It:

  1. loads the Delta merchant (run ``seed_delta_merchant`` first),
  2. authenticates (``/auth/login``) — the auth smoke test,
  3. registers ONE B2C invoice (100 ETB @ VAT15) and prints the IRN + QR,
  4. registers a SALES RECEIPT for that invoice and prints the RRN.

Run:  python -m scripts.sandbox_smoke
Exit code 0 = invoice registered (receipt result reported separately, since the
receipt path is coded-but-unvalidated and may need field tweaks on first run).
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import mor_client, registration  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import FiscalStatus  # noqa: E402
from app.secrets_backend import get_secrets_backend  # noqa: E402

DELTA_TIN = "0107184904"


def _line(title: str) -> None:
    print("\n" + "=" * 64 + f"\n  {title}\n" + "=" * 64)


def main() -> int:
    session = SessionLocal()
    try:
        try:
            merchant = registration.get_merchant_by_tin(session, DELTA_TIN)
        except registration.MerchantNotFound:
            print("[smoke] Delta merchant not found. Run: python -m scripts.seed_delta_merchant")
            return 2

        # 1) Auth smoke test ------------------------------------------------- #
        _line("1) AUTH  /auth/login")
        secrets = get_secrets_backend().load_merchant_credentials(merchant)
        try:
            token = mor_client.login(merchant, secrets)
            print(f"[smoke] login OK — token {token[:12]}…")
        except Exception as exc:
            print(f"[smoke] login FAILED: {exc}")
            print("[smoke] Check DELTA_EIMS_* env vars + the cert/key paths, then retry.")
            return 3

        # 2) Register a B2C invoice ----------------------------------------- #
        _line("2) REGISTER INVOICE  /v1/register  (100 ETB @ VAT15)")
        inv_ref = f"SMOKE-INV-{int(time.time())}"
        tx = {
            "transaction_ref": inv_ref,
            "amount": 100,
            "currency": "ETB",
            "payment_mode": "CASH",
            "buyer": {"legal_name": "Smoke Test Buyer"},
            "items": [{
                "item_code": "SMOKE",
                "product_description": "Smoke test service",
                "unit_price": 100,
                "quantity": 1,
                "discount": 0,
                "nature_of_supplies": "service",
                "unit": "PCS",
                "tax_code": "VAT15",
            }],
        }
        doc = registration.register_invoice_for_merchant(session, merchant, tx)
        print(f"[smoke] status   : {doc.fiscal_status.value}")
        print(f"[smoke] IRN      : {doc.irn}")
        print(f"[smoke] doc no   : {doc.document_number}")
        print(f"[smoke] QR       : {'present (' + str(len(doc.qr_b64)) + ' b64 chars)' if doc.qr_b64 else 'MISSING'}")
        if doc.error:
            print(f"[smoke] error    : {doc.error}")
        if doc.fiscal_status != FiscalStatus.REGISTERED or not doc.irn:
            print("[smoke] invoice not registered — fix the error above and retry.")
            return 4

        # 3) Register a sales receipt for that invoice ---------------------- #
        _line("3) REGISTER RECEIPT  /v1/receipt/sales")
        rcpt_ref = f"SMOKE-RCP-{int(time.time())}"
        rcpt = {
            "transaction_ref": rcpt_ref,
            "collected_amount": 100,
            "currency": "ETB",
            "reason": "Smoke test receipt",
            "invoices": [{
                "invoice_irn": doc.irn,
                "payment_coverage": "FULL",
                "invoice_paid_amount": 100,
                "total_amount": 100,
            }],
            "transaction_details": {"mode_of_payment": "CASH", "collector_name": "Smoke Test"},
        }
        rdoc = registration.register_receipt_for_document(session, merchant, rcpt)
        print(f"[smoke] status   : {rdoc.fiscal_status.value}")
        print(f"[smoke] RRN      : {rdoc.rrn}")
        if rdoc.error:
            print(f"[smoke] error    : {rdoc.error}")
            print("[smoke] NOTE: the /v1/receipt/sales shape is sandbox-unvalidated — if MoR")
            print("        rejects it, adjust app/receipt_builder.py field names per the response.")

        _line("DONE")
        print(f"[smoke] invoice IRN: {doc.irn}")
        print(f"[smoke] receipt RRN: {rdoc.rrn}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
