"""Receipt fiscal-core — FastAPI application entrypoint.

API-first fiscalization for Ethiopia's MoR EIMS. Multi-tenant aggregator: each
merchant (tenant) holds its own TIN / certificate / credentials and an
independent invoice chain. Route handlers are sync ``def`` (run in FastAPI's
threadpool) because the MoR transport layer is synchronous (byte-exact parity
with the validated Delta client).

Run (dev):  uvicorn app.main:app --reload
OpenAPI:    /docs   (Swagger)   ·   /redoc
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app import registration, webapp
from app.config import get_settings
from app.db import get_session
from app.models import Document, FiscalStatus, Merchant
from app.routers import admin, invoices, merchants

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("receipt")

app = FastAPI(
    title="Receipt — MoR EIMS Fiscal Core",
    version="0.1.0",
    description=(
        "API-first fiscalization for Ethiopia's Ministry of Revenue EIMS. "
        "Register/cancel/verify invoices, sales receipts, and credit/debit notes "
        "on behalf of many merchants (multi-tenant BSP aggregator)."
    ),
)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev-only-change-me"),
    same_site="lax",
)

app.include_router(merchants.router)
app.include_router(invoices.router)
app.include_router(admin.router)
app.include_router(webapp.router)

# Marketing site (Receipt-landing) served at "/" when bundled into the image.
_LANDING = os.environ.get(
    "LANDING_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "landing"),
)

# Vite build output references /assets/*; mount it when the React landing is bundled.
_LANDING_ASSETS = os.path.join(_LANDING, "assets")
if os.path.isdir(_LANDING_ASSETS):
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=_LANDING_ASSETS), name="landing-assets")


@app.get("/", include_in_schema=False)
def landing_index():
    index = os.path.join(_LANDING, "index.html")
    if os.path.isfile(index):
        return FileResponse(index)
    return RedirectResponse(url="/app/login")


@app.get("/get-started.html", include_in_schema=False)
def landing_get_started():
    page = os.path.join(_LANDING, "get-started.html")
    if os.path.isfile(page):
        return FileResponse(page)
    return RedirectResponse(url="/app/login")


@app.get("/demo.html", include_in_schema=False)
def landing_demo():
    page = os.path.join(_LANDING, "demo.html")
    if os.path.isfile(page):
        return FileResponse(page)
    return RedirectResponse(url="/")


# --------------------------------------------------------------------------- #
# Landing-page live demo: registers a REAL sandbox invoice + sales receipt on
# the demo merchant's chain so the row appears on the MoR portal moments later.
# Public but rate-limited; sandbox-only by ops policy (demo merchant creds).
# --------------------------------------------------------------------------- #
_DEMO_TIN = os.environ.get("DEMO_MERCHANT_TIN", "0107184904")
_DEMO_HOURLY_CAP = int(os.environ.get("DEMO_HOURLY_CAP", "6"))
_DEMO_ITEMS = [
    ("MACCHIATO", "Macchiato", 70.0, 2),
    ("AMBO", "Ambo water", 40.0, 1),
]


@app.post("/demo/charge", tags=["demo"])
def demo_charge(db: Session = Depends(get_session)) -> JSONResponse:
    merchant = db.execute(
        select(Merchant).where(Merchant.tin == _DEMO_TIN)
    ).scalar_one_or_none()
    if merchant is None:
        return JSONResponse({"ok": False, "reason": "demo merchant not configured"}, status_code=503)

    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = db.execute(
        select(func.count())
        .select_from(Document)
        .where(
            Document.merchant_id == merchant.id,
            Document.transaction_ref.like("DEMO-%"),
            Document.created_at >= hour_ago,
        )
    ).scalar_one()
    if recent >= _DEMO_HOURLY_CAP:
        return JSONResponse({"ok": False, "reason": "demo limit reached — try again in an hour"}, status_code=429)

    tax_code = merchant.tax_code or "VAT15"
    items = [
        {
            "item_code": code, "product_description": name,
            "unit_price": price, "quantity": qty, "discount": 0.0,
            "nature_of_supplies": "goods", "unit": "PCS", "tax_code": tax_code,
        }
        for code, name, price, qty in _DEMO_ITEMS
    ]
    total = round(sum(i["unit_price"] * i["quantity"] for i in items), 2)
    tx = {
        "transaction_ref": f"DEMO-{uuid4().hex[:12]}",
        "amount": total, "currency": "ETB", "payment_mode": "CASH",
        "items": items, "buyer": None,
    }
    try:
        doc = registration.register_invoice_for_merchant(db, merchant, tx)
    except Exception as exc:  # transport/config errors -> soft failure, FE replays
        logger.warning("demo.charge failed: %s", exc)
        return JSONResponse({"ok": False, "reason": str(exc)[:200]}, status_code=502)

    if doc.fiscal_status != FiscalStatus.REGISTERED or not doc.irn:
        return JSONResponse({"ok": False, "reason": (doc.error or "registration failed")[:200]}, status_code=502)

    rrn = None
    try:
        rcpt = registration.register_receipt_for_document(
            db, merchant,
            {
                "transaction_ref": f"RCP-{doc.transaction_ref}",
                "collected_amount": float(doc.amount or total),
                "invoices": [{
                    "invoice_irn": doc.irn,
                    "payment_coverage": "FULL",
                    "invoice_paid_amount": float(doc.amount or total),
                    "total_amount": float(doc.amount or total),
                }],
                "transaction_details": {"mode_of_payment": "CASH"},
            },
        )
        rrn = rcpt.rrn
    except Exception as exc:  # receipt is best-effort; invoice already registered
        logger.warning("demo.charge receipt failed: %s", exc)

    pre = round(total / 1.15, 2)
    return JSONResponse({
        "ok": True,
        "irn": doc.irn,
        "rrn": rrn,
        "docNo": doc.document_number,
        "date": (doc.registered_at or datetime.now(timezone.utc)).isoformat(),
        "qr": doc.qr_b64,
        "total": total,
        "preTax": pre,
        "vat": round(total - pre, 2),
        "items": [
            {"name": name, "qty": qty, "unit": price, "total": round(price * qty, 2)}
            for _, name, price, qty in _DEMO_ITEMS
        ],
    })


@app.get("/healthz", tags=["health"])
def healthz() -> dict:
    """Liveness probe (no DB/MoR dependency)."""
    return {"status": "ok", "service": "receipt-fiscal-core", "env": settings.ENV}


@app.on_event("startup")
def _startup() -> None:
    logger.info("receipt fiscal-core starting env=%s secrets_backend=%s", settings.ENV, settings.SECRETS_BACKEND)
