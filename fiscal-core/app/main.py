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

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from app import webapp
from app.config import get_settings
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


@app.get("/healthz", tags=["health"])
def healthz() -> dict:
    """Liveness probe (no DB/MoR dependency)."""
    return {"status": "ok", "service": "receipt-fiscal-core", "env": settings.ENV}


@app.on_event("startup")
def _startup() -> None:
    logger.info("receipt fiscal-core starting env=%s secrets_backend=%s", settings.ENV, settings.SECRETS_BACKEND)
