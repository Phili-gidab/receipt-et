"""Receipt SaaS web app — server-rendered POS UI (slip.et-equivalent).

Lightweight, server-rendered pages (Jinja + tiny vanilla JS) so it stays snappy
on the ~2 Mbps Ethio Telecom host. It reuses the fiscal core directly (same
process / DB) rather than going over HTTP: the POS posts a cart, we call the
:mod:`app.registration` service to register the invoice + sales receipt with MoR,
then render the QR receipt. Design mirrors ``Receipt-landing`` (dark + green,
IBM Plex Mono / Archivo, receipt motif).

Routes (mounted at ``/app``):
  /app/login  /app/verify  /app/logout        — phone + OTP (OTP is a DEV STUB
                                                 until an SMS gateway is wired)
  /app                                        — dashboard (today's sales)
  /app/pos    /app/pos/checkout               — cashier → issue fiscal receipt
  /app/receipt/{id}  /app/receipt/{id}/print  — QR receipt view + thermal print
  /app/receipts                               — searchable history
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import mor_client, printing, registration
from app.db import get_session
from app.models import Document, FiscalStatus, Merchant, MerchantSecret
from app.secrets_backend import get_secrets_backend

router = APIRouter(prefix="/app", tags=["webapp"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


# --------------------------------------------------------------------------- #
# Session / auth helpers  (OTP is a dev stub — swap for a real SMS gateway)
# --------------------------------------------------------------------------- #
def _norm_phone(phone: str) -> str:
    p = "".join(ch for ch in (phone or "") if ch.isdigit() or ch == "+").lstrip("+")
    if p.startswith("0"):
        p = "251" + p[1:]
    return p


def _find_merchant_by_phone(db: Session, ident: str) -> Merchant | None:
    """Find by TIN (10 digits) or phone. Dev fallback: single-merchant DB."""
    digits = "".join(ch for ch in (ident or "") if ch.isdigit())
    if len(digits) == 10:
        m = db.execute(select(Merchant).where(Merchant.tin == digits)).scalar_one_or_none()
        if m is not None:
            return m
    want = _norm_phone(ident)[-9:]
    if want:
        for m in db.execute(select(Merchant)).scalars():
            if m.phone and _norm_phone(m.phone)[-9:] == want:
                return m
    rows = list(db.execute(select(Merchant)).scalars())
    return rows[0] if len(rows) == 1 else None


def _current(request: Request, db: Session) -> Merchant | None:
    mid = request.session.get("merchant_id")
    return db.get(Merchant, mid) if mid else None


def _ctx(request: Request, merchant: Merchant, **extra) -> dict:
    return {"request": request, "m": merchant, "brand": "Receipt", **extra}


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(request: Request, phone: str = Form(...), db: Session = Depends(get_session)):
    merchant = _find_merchant_by_phone(db, phone)
    if merchant is None:
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "No business found for that number. Ask us to onboard you."},
            status_code=404,
        )
    request.session["pending_mid"] = merchant.id
    request.session["pending_phone"] = _norm_phone(phone)
    # DEV STUB: a real build texts a random code here.
    request.session["dev_code"] = "000000"
    return RedirectResponse(url="/app/verify", status_code=303)


@router.get("/verify", response_class=HTMLResponse)
def verify_form(request: Request):
    if not request.session.get("pending_mid"):
        return RedirectResponse(url="/app/login", status_code=303)
    return templates.TemplateResponse(
        request, "verify.html",
        {"phone": request.session.get("pending_phone"),
         "dev_code": request.session.get("dev_code"), "error": None},
    )


@router.post("/verify")
def verify_submit(request: Request, code: str = Form(...)):
    mid = request.session.get("pending_mid")
    if not mid:
        return RedirectResponse(url="/app/login", status_code=303)
    code = (code or "").strip()
    # DEV STUB: accept the shown dev code or any 6 digits.
    if code != request.session.get("dev_code") and not (code.isdigit() and len(code) == 6):
        return templates.TemplateResponse(
            request, "verify.html",
            {"phone": request.session.get("pending_phone"),
             "dev_code": request.session.get("dev_code"), "error": "Wrong code — try again."},
            status_code=401,
        )
    request.session["merchant_id"] = mid
    dest = request.session.pop("post_verify", "/app")
    for k in ("pending_mid", "pending_phone", "dev_code"):
        request.session.pop(k, None)
    return RedirectResponse(url=dest, status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/app/login", status_code=303)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_session)):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)

    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    q = select(Document).where(Document.merchant_id == merchant.id, Document.created_at >= start)
    today = list(db.execute(q.order_by(Document.created_at.desc())).scalars())
    registered = [d for d in today if d.fiscal_status == FiscalStatus.REGISTERED]
    total = sum(float(d.amount or 0) for d in registered)
    recent = list(db.execute(
        select(Document).where(Document.merchant_id == merchant.id)
        .order_by(Document.created_at.desc()).limit(8)
    ).scalars())
    return templates.TemplateResponse(request, "dashboard.html", _ctx(
        request, merchant,
        stat_count=len(today), stat_registered=len(registered), stat_total=total,
        recent=recent,
    ))


# --------------------------------------------------------------------------- #
# POS
# --------------------------------------------------------------------------- #
@router.get("/pos", response_class=HTMLResponse)
def pos(request: Request, db: Session = Depends(get_session)):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    return templates.TemplateResponse(request, "pos.html", _ctx(request, merchant, tax_code=merchant.tax_code or "VAT15"))


@router.post("/pos/checkout")
def checkout(
    request: Request,
    cart: str = Form(...),
    payment_method: str = Form("CASH"),
    buyer_tin: str = Form(""),
    buyer_name: str = Form(""),
    db: Session = Depends(get_session),
):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)

    lines = json.loads(cart or "[]")
    items = [{
        "item_code": (str(li.get("code") or li.get("name") or "ITEM"))[:15],
        "product_description": str(li.get("name") or "Item")[:300],
        "unit_price": float(li.get("price") or 0),
        "quantity": float(li.get("qty") or 1),
        "discount": float(li.get("discount") or 0),
        "nature_of_supplies": "goods",
        "unit": "PCS",
        "tax_code": merchant.tax_code or "VAT15",
    } for li in lines]
    total = sum(i["unit_price"] * i["quantity"] - i["discount"] for i in items)

    tx = {
        "transaction_ref": f"POS-{uuid.uuid4().hex[:12]}",
        "amount": round(total, 2),
        "currency": "ETB",
        "payment_mode": "CASH" if payment_method.upper() in ("CASH", "TELEBIRR", "MOBILE") else "CREDIT",
        "items": items,
        "buyer": ({"legal_name": buyer_name.strip(), "tin": buyer_tin.strip()}
                  if buyer_tin.strip() else ({"legal_name": buyer_name.strip()} if buyer_name.strip() else None)),
    }
    try:
        doc = registration.register_invoice_for_merchant(db, merchant, tx)
        # If the invoice registered, also issue a sales receipt (best-effort).
        if doc.fiscal_status == FiscalStatus.REGISTERED and doc.irn:
            try:
                registration.register_receipt_for_document(db, merchant, {
                    "transaction_ref": f"RCP-{doc.transaction_ref}",
                    "collected_amount": float(doc.amount or total),
                    "invoices": [{"invoice_irn": doc.irn, "payment_coverage": "FULL",
                                  "invoice_paid_amount": float(doc.amount or total),
                                  "total_amount": float(doc.amount or total)}],
                    "transaction_details": {"mode_of_payment": tx["payment_mode"]},
                })
            except registration.RegistrationError:
                pass
    except Exception as exc:  # RegistrationError, missing secrets (KeyError), transport, …
        return templates.TemplateResponse(
            request, "pos.html",
            _ctx(request, merchant, tax_code=merchant.tax_code or "VAT15", error=str(exc)),
            status_code=400,
        )
    return RedirectResponse(url=f"/app/receipt/{doc.id}", status_code=303)


# --------------------------------------------------------------------------- #
# Receipt view + print + history
# --------------------------------------------------------------------------- #
def _load_doc(request: Request, db: Session, doc_id: int):
    merchant = _current(request, db)
    if merchant is None:
        return None, None
    doc = db.get(Document, doc_id)
    if doc is None or doc.merchant_id != merchant.id:
        return merchant, None
    return merchant, doc


@router.get("/receipt/{doc_id}", response_class=HTMLResponse)
def receipt_view(request: Request, doc_id: int, db: Session = Depends(get_session)):
    merchant, doc = _load_doc(request, db, doc_id)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    if doc is None:
        return RedirectResponse(url="/app/receipts", status_code=303)
    payload = json.loads(doc.payload_json) if doc.payload_json else {}
    return templates.TemplateResponse(request, "receipt.html", _ctx(
        request, merchant, doc=doc, payload=payload,
        registered=(doc.fiscal_status == FiscalStatus.REGISTERED),
    ))


@router.get("/receipt/{doc_id}/print", response_class=HTMLResponse)
def receipt_print(request: Request, doc_id: int, fmt: str = "thermal", db: Session = Depends(get_session)):
    merchant, doc = _load_doc(request, db, doc_id)
    if merchant is None or doc is None:
        return RedirectResponse(url="/app/receipts", status_code=303)
    html = printing.render_invoice_html(doc, merchant, fmt=fmt)
    return HTMLResponse(content=html)


@router.get("/receipts", response_class=HTMLResponse)
def receipts(request: Request, q: str = "", db: Session = Depends(get_session)):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    stmt = select(Document).where(Document.merchant_id == merchant.id)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(func.coalesce(Document.irn, "").ilike(like)
                          | func.coalesce(Document.transaction_ref, "").ilike(like))
    docs = list(db.execute(stmt.order_by(Document.created_at.desc()).limit(100)).scalars())
    return templates.TemplateResponse(request, "receipts.html", _ctx(request, merchant, docs=docs, q=q))


# --------------------------------------------------------------------------- #
# Signup (dev OTP - code shown on screen until an SMS gateway is wired)
# --------------------------------------------------------------------------- #
@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request):
    return templates.TemplateResponse(request, "signup.html", {"error": None})


@router.post("/signup")
def signup_submit(
    request: Request,
    tin: str = Form(...),
    legal_name: str = Form(...),
    phone: str = Form(...),
    db: Session = Depends(get_session),
):
    from sqlalchemy import select as _select
    tin = "".join(ch for ch in tin if ch.isdigit())
    if len(tin) != 10:
        return templates.TemplateResponse(request, "signup.html",
            {"error": "TIN must be exactly 10 digits.", "tin": tin,
             "legal_name": legal_name, "phone": phone}, status_code=422)
    exists = db.execute(_select(Merchant).where(Merchant.tin == tin)).scalar_one_or_none()
    if exists is not None:
        return templates.TemplateResponse(request, "signup.html",
            {"error": "A business with this TIN already exists - sign in instead.",
             "tin": tin, "legal_name": legal_name, "phone": phone}, status_code=409)
    merchant = Merchant(
        tin=tin, legal_name=legal_name.strip(), phone=_norm_phone(phone),
        system_type="POS", tax_code="VAT15", price_vat_inclusive=True,
        base_url="https://core.mor.gov.et", tls_verify=False, status="active",
    )
    merchant.secret = MerchantSecret()
    db.add(merchant)
    db.commit()
    request.session["pending_mid"] = merchant.id
    request.session["pending_phone"] = _norm_phone(phone)
    request.session["dev_code"] = "000000"   # DEV STUB: swap for SMS gateway
    request.session["post_verify"] = "/app/settings"
    return RedirectResponse(url="/app/verify", status_code=303)


# --------------------------------------------------------------------------- #
# Settings - EIRMS credentials, INSA key/cert, seller record
# --------------------------------------------------------------------------- #
def _secrets_dir(merchant: Merchant) -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "secrets", merchant.tin)
    os.makedirs(d, exist_ok=True)
    return d


def _write_secret_file(merchant: Merchant, name: str, value: str) -> str:
    path = os.path.join(_secrets_dir(merchant), name)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(value.strip() + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _settings_ctx(request: Request, merchant: Merchant, ok=None, error=None) -> dict:
    sec = merchant.secret
    key_ref = sec.private_key_ref if sec else None
    cert_ref = sec.certificate_ref if sec else None
    cert_note = ""
    cert_present = bool(cert_ref and os.path.isfile(cert_ref))
    if cert_present:
        try:
            from cryptography import x509
            with open(cert_ref, "rb") as fh:
                cert = x509.load_pem_x509_certificate(fh.read())
            cert_note = "expires " + cert.not_valid_after_utc.strftime("%d %b %Y")
        except Exception:
            cert_note = ""
    return _ctx(request, merchant,
        s={"client_id": bool(sec and sec.client_id),
           "client_secret": bool(sec and sec.client_secret),
           "api_key": bool(sec and sec.api_key)},
        key_present=bool(key_ref and os.path.isfile(key_ref)),
        cert_present=cert_present, cert_note=cert_note, ok=ok, error=error)


@router.get("/settings", response_class=HTMLResponse)
def settings_form(request: Request, db: Session = Depends(get_session)):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    return templates.TemplateResponse(request, "settings.html", _settings_ctx(request, merchant))


def _apply_settings(request, merchant, db, form):
    if merchant.secret is None:
        merchant.secret = MerchantSecret(merchant_id=merchant.id)
        db.add(merchant.secret)
    sec = merchant.secret
    # credentials: blank input = keep existing
    if form.get("client_id", "").strip():
        sec.client_id = form["client_id"].strip()
    if form.get("client_secret", "").strip():
        sec.client_secret = _write_secret_file(merchant, "client_secret.txt", form["client_secret"])
    if form.get("api_key", "").strip():
        sec.api_key = _write_secret_file(merchant, "api_key.txt", form["api_key"])
    if form.get("private_key_pem", "").strip():
        sec.private_key_ref = _write_secret_file(merchant, "private_key.key", form["private_key_pem"])
    if form.get("certificate_pem", "").strip():
        sec.certificate_ref = _write_secret_file(merchant, "certificate.pem", form["certificate_pem"])
    # merchant fields — a field ABSENT from the form must never clear stored
    # data (partial/programmatic posts would silently wipe the seller record,
    # which then fails the VAT rule / MoR 1028). Present-but-blank does clear.
    merchant.base_url = form.get("base_url", "").strip() or merchant.base_url
    merchant.system_type = form.get("system_type") or merchant.system_type
    if "system_number" in form:
        merchant.system_number = form["system_number"].strip() or None
    if "legal_name" in form:  # full settings form present -> checkbox semantics valid
        merchant.tls_verify = form.get("tls_verify") == "1"
        merchant.legal_name = form["legal_name"].strip() or merchant.legal_name
    for f in ("vat_number", "region", "city", "wereda", "default_buyer_id_number"):
        if f in form:
            setattr(merchant, f, form[f].strip() or None)
    merchant.tax_code = form.get("tax_code") or merchant.tax_code
    if "default_buyer_id_type" in form:
        merchant.default_buyer_id_type = form["default_buyer_id_type"] or None
    db.commit()
    mor_client.clear_token_cache(merchant.id)


@router.post("/settings")
async def settings_save(request: Request, db: Session = Depends(get_session)):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    form = dict(await request.form())
    _apply_settings(request, merchant, db, form)
    return templates.TemplateResponse(request, "settings.html",
        _settings_ctx(request, merchant, ok="Settings saved."))


@router.post("/settings/test")
async def settings_test(request: Request, db: Session = Depends(get_session)):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    form = dict(await request.form())
    _apply_settings(request, merchant, db, form)
    try:
        secrets = get_secrets_backend().load_merchant_credentials(merchant)
        missing = [k for k in ("client_id", "client_secret", "api_key", "private_key", "certificate")
                   if not secrets.get(k)]
        if missing:
            raise RuntimeError("Missing: " + ", ".join(missing))
        token = mor_client.login(merchant, secrets)
        return templates.TemplateResponse(request, "settings.html",
            _settings_ctx(request, merchant, ok="Connected to MoR - login OK (token %s...)." % token[:10]))
    except Exception as exc:
        return templates.TemplateResponse(request, "settings.html",
            _settings_ctx(request, merchant, error="Connection test failed: %s" % str(exc)[:400]))
