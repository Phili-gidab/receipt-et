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
    attention = list(db.execute(
        select(Document).where(
            Document.merchant_id == merchant.id,
            Document.fiscal_status.in_([FiscalStatus.FAILED, FiscalStatus.PENDING]),
        ).order_by(Document.created_at.desc()).limit(6)
    ).scalars())
    return templates.TemplateResponse(request, "dashboard.html", _ctx(
        request, merchant,
        stat_count=len(today), stat_registered=len(registered), stat_total=total,
        recent=recent, attention=attention,
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


def share_token(doc_id: int) -> str:
    """Unguessable token for the public share link (HMAC over SESSION_SECRET)."""
    import hashlib
    import hmac as _hmac
    secret = os.environ.get("SESSION_SECRET", "dev-only-change-me").encode()
    return _hmac.new(secret, f"share:{doc_id}".encode(), hashlib.sha256).hexdigest()[:20]


def _doc_by_irn(db: Session, merchant: Merchant, irn: str | None):
    if not irn:
        return None
    return db.execute(
        select(Document).where(Document.merchant_id == merchant.id, Document.irn == irn)
    ).scalar_one_or_none()


@router.get("/receipt/{doc_id}", response_class=HTMLResponse)
def receipt_view(request: Request, doc_id: int, ok: str = "", err: str = "",
                 db: Session = Depends(get_session)):
    merchant, doc = _load_doc(request, db, doc_id)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    if doc is None:
        return RedirectResponse(url="/app/receipts", status_code=303)
    payload = json.loads(doc.payload_json) if doc.payload_json else {}

    # Cross-links: RCP -> invoice(s) it paid; CRE/DEB -> the original invoice;
    # INV -> any notes/receipts that reference it.
    related = None
    if doc.doc_type == "RCP":
        inv_rows = payload.get("Invoices") or []
        related = _doc_by_irn(db, merchant, inv_rows[0].get("InvoiceIRN") if inv_rows else None)
    elif doc.doc_type in ("CRE", "DEB"):
        related = _doc_by_irn(db, merchant, (payload.get("ReferenceDetails") or {}).get("RelatedDocument"))
    children = []
    if doc.doc_type == "INV" and doc.irn:
        like = f'%{doc.irn}%'
        children = list(db.execute(
            select(Document)
            .where(Document.merchant_id == merchant.id, Document.id != doc.id,
                   func.coalesce(Document.payload_json, "").like(like))
            .order_by(Document.created_at.desc()).limit(10)
        ).scalars())

    return templates.TemplateResponse(request, "receipt.html", _ctx(
        request, merchant, doc=doc, payload=payload,
        registered=(doc.fiscal_status == FiscalStatus.REGISTERED),
        related=related, children=children,
        share_url=f"/r/{doc.id}/{share_token(doc.id)}",
        ok=ok or None, err=err or None,
    ))


@router.get("/receipt/{doc_id}/print", response_class=HTMLResponse)
def receipt_print(request: Request, doc_id: int, fmt: str = "thermal", db: Session = Depends(get_session)):
    merchant, doc = _load_doc(request, db, doc_id)
    if merchant is None or doc is None:
        return RedirectResponse(url="/app/receipts", status_code=303)
    if doc.doc_type == "RCP":
        html = printing.render_receipt_html(doc, merchant, fmt=fmt)
    else:
        html = printing.render_invoice_html(doc, merchant, fmt=fmt)
    return HTMLResponse(content=html)


def _back_to_doc(doc_id: int, *, ok: str = "", err: str = "") -> RedirectResponse:
    from urllib.parse import quote
    qs = f"?ok={quote(ok)}" if ok else (f"?err={quote(err)}" if err else "")
    return RedirectResponse(url=f"/app/receipt/{doc_id}{qs}", status_code=303)


@router.post("/receipt/{doc_id}/void")
def receipt_void(request: Request, doc_id: int, reason_code: str = Form("3"),
                 remark: str = Form(""), db: Session = Depends(get_session)):
    merchant, doc = _load_doc(request, db, doc_id)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    if doc is None:
        return RedirectResponse(url="/app/receipts", status_code=303)
    if doc.doc_type not in ("INV", "CRE", "DEB") or not doc.irn:
        return _back_to_doc(doc_id, err="Only registered invoices/notes can be voided.")
    try:
        registration.cancel_invoice_for_document(
            db, merchant, doc.irn, reason_code=reason_code, remark=remark.strip(),
        )
        return _back_to_doc(doc_id, ok="Voided — cancellation registered with MoR.")
    except Exception as exc:
        return _back_to_doc(doc_id, err=f"Void failed: {str(exc)[:250]}")


@router.post("/receipt/{doc_id}/refund")
def receipt_refund(request: Request, doc_id: int, reason: str = Form(""),
                   db: Session = Depends(get_session)):
    merchant, doc = _load_doc(request, db, doc_id)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    if doc is None:
        return RedirectResponse(url="/app/receipts", status_code=303)
    if doc.doc_type != "INV" or doc.fiscal_status != FiscalStatus.REGISTERED or not doc.irn:
        return _back_to_doc(doc_id, err="Refunds need a registered invoice.")
    if not doc.amount:
        return _back_to_doc(doc_id, err="Original amount unknown — cannot refund.")

    # MoR rule 7020: a credit note's items must MIRROR the original invoice's
    # items (product/qty/tax code/unit) — rebuild them from the stored payload.
    # Feeding TotalLineAmount/qty back through the builder re-finds the exact
    # same UnitPrice, so the note reproduces the original lines to the cent.
    try:
        orig_items = (json.loads(doc.payload_json or "{}").get("ItemList")) or []
    except Exception:
        orig_items = []
    if not orig_items:
        return _back_to_doc(doc_id, err="Original items unavailable — cannot refund.")
    items = [{
        "item_code": it.get("ItemCode") or "",
        "product_description": it.get("ProductDescription") or "",
        "unit_price": float(it.get("TotalLineAmount") or 0) / float(it.get("Quantity") or 1),
        "quantity": it.get("Quantity") or 1,
        "discount": 0.0,
        "nature_of_supplies": it.get("NatureOfSupplies") or "goods",
        "unit": it.get("Unit") or "PCS",
        "tax_code": it.get("TaxCode") or (merchant.tax_code or "VAT15"),
    } for it in orig_items]

    # idempotent on success; a FAILED attempt must not block the retry
    base_ref = f"CRE-{doc.transaction_ref}"
    prior = list(db.execute(
        select(Document).where(Document.merchant_id == merchant.id,
                               Document.transaction_ref.like(f"{base_ref}%"))
    ).scalars())
    done = next((p for p in prior if p.fiscal_status == FiscalStatus.REGISTERED), None)
    if done is not None:
        return _back_to_doc(done.id, ok="Already refunded — this is the credit note.")
    ref = base_ref if not prior else f"{base_ref}-{uuid.uuid4().hex[:4]}"

    note = {
        "transaction_ref": ref,
        "amount": float(doc.amount),
        "currency": doc.currency or "ETB",
        "payment_mode": "CASH",
        "related_irn": doc.irn,
        "reason": (reason.strip() or "Refund / return of goods")[:300],
        "items": items,
    }
    try:
        cre = registration.issue_credit_note(db, merchant, note)
    except Exception as exc:
        return _back_to_doc(doc_id, err=f"Refund failed: {str(exc)[:250]}")
    if cre.fiscal_status == FiscalStatus.REGISTERED:
        return _back_to_doc(cre.id, ok="Refund registered with MoR (credit note).")
    return _back_to_doc(cre.id, err=f"Credit note rejected: {(cre.error or '')[:250]}")


# --------------------------------------------------------------------------- #
# Z-report — day-close summary (Africa/Addis_Ababa day, UTC+3)
# --------------------------------------------------------------------------- #
@router.get("/zreport", response_class=HTMLResponse)
def zreport(request: Request, date: str = "", db: Session = Depends(get_session)):
    from datetime import timedelta

    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    addis = timezone(timedelta(hours=3))
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date() if date else datetime.now(addis).date()
    except ValueError:
        day = datetime.now(addis).date()
    start_local = datetime(day.year, day.month, day.day, tzinfo=addis)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(days=1)

    docs = list(db.execute(
        select(Document).where(
            Document.merchant_id == merchant.id,
            Document.created_at >= start_utc,
            Document.created_at < end_utc,
        ).order_by(Document.created_at.asc())
    ).scalars())

    def _vat_of(d: Document) -> float:
        try:
            return float((json.loads(d.payload_json or "{}").get("ValueDetails") or {}).get("TaxValue") or 0)
        except Exception:
            return 0.0

    inv = [d for d in docs if d.doc_type == "INV" and d.fiscal_status == FiscalStatus.REGISTERED]
    cre = [d for d in docs if d.doc_type == "CRE" and d.fiscal_status == FiscalStatus.REGISTERED]
    gross = sum(float(d.amount or 0) for d in inv)
    refunds = sum(float(d.amount or 0) for d in cre)
    vat_out = sum(_vat_of(d) for d in inv) - sum(_vat_of(d) for d in cre)
    voided = [d for d in docs if d.fiscal_status == FiscalStatus.CANCELLED]
    failed = [d for d in docs if d.fiscal_status == FiscalStatus.FAILED]

    return templates.TemplateResponse(request, "zreport.html", _ctx(
        request, merchant,
        day=day.strftime("%d %b %Y"), day_iso=day.isoformat(),
        prev_day=(day - timedelta(days=1)).isoformat(),
        next_day=(day + timedelta(days=1)).isoformat(),
        docs=docs, inv_count=len(inv), gross=gross, refunds=refunds,
        net=gross - refunds, vat_out=vat_out,
        rcp_count=sum(1 for d in docs if d.doc_type == "RCP" and d.fiscal_status == FiscalStatus.REGISTERED),
        voided_count=len(voided), failed_count=len(failed),
    ))


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
