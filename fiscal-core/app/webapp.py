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
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import mor_client, pos, printing, registration
from app.db import get_session
from app.models import Buyer, Document, FiscalStatus, Merchant, MerchantSecret, Product
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

    # Last-7-days series + week totals (Addis calendar; same math as reports).
    from app import reports
    today_local = datetime.now(reports.ADDIS_TZ).date()
    week = reports.range_report(db, merchant, today_local - timedelta(days=6), today_local)

    # Compliance health: the chain head must equal the InvoiceCounter of the
    # newest registered chained document. (Comparing against a local doc COUNT
    # is wrong for merchants whose MoR counter predates this database — Delta's
    # did — and would show a permanent false mismatch.)
    recent_chained = list(db.execute(
        select(Document.payload_json).where(
            Document.merchant_id == merchant.id,
            Document.doc_type.in_(["INV", "CRE", "DEB"]),
            Document.fiscal_status.in_([FiscalStatus.REGISTERED, FiscalStatus.CANCELLED]),
        ).order_by(Document.created_at.desc()).limit(50)
    ).scalars())
    last_counter = 0
    for pj in recent_chained:
        try:
            c = int((json.loads(pj or "{}").get("SourceSystem") or {}).get("InvoiceCounter") or 0)
        except Exception:
            c = 0
        last_counter = max(last_counter, c)
    failed_total = db.execute(
        select(func.count(Document.id)).where(
            Document.merchant_id == merchant.id, Document.fiscal_status == FiscalStatus.FAILED,
        )
    ).scalar_one()
    products_count = db.execute(
        select(func.count(Product.id)).where(Product.merchant_id == merchant.id, Product.active.is_(True))
    ).scalar_one()
    buyers_count = db.execute(
        select(func.count(Buyer.id)).where(Buyer.merchant_id == merchant.id)
    ).scalar_one()

    swept = request.query_params.get("swept") or ""
    sweep_ok = request.query_params.get("sweep_ok") or ""
    sweep_bad = request.query_params.get("sweep_bad") or ""

    return templates.TemplateResponse(request, "dashboard.html", _ctx(
        request, merchant,
        stat_count=len(today), stat_registered=len(registered), stat_total=total,
        recent=recent, attention=attention,
        week=week, week_days=week.days, top_items=week.top_items[:3],
        chain_counter=(merchant.chain.counter if merchant.chain else 0),
        last_counter=last_counter, failed_total=failed_total,
        products_count=products_count, buyers_count=buyers_count,
        swept=swept, sweep_ok=sweep_ok, sweep_bad=sweep_bad,
    ))


# --------------------------------------------------------------------------- #
# POS
# --------------------------------------------------------------------------- #
def _pos_ctx(request: Request, merchant: Merchant, db: Session, **extra) -> dict:
    """POS template context: catalog grid + saved-buyer picker ride along."""
    products = list(db.execute(
        select(Product).where(Product.merchant_id == merchant.id, Product.active.is_(True))
        .order_by(Product.name.asc())
    ).scalars())
    buyers = list(db.execute(
        select(Buyer).where(Buyer.merchant_id == merchant.id)
        .order_by(Buyer.last_used_at.desc().nullslast(), Buyer.name.asc()).limit(40)
    ).scalars())
    return _ctx(request, merchant, tax_code=merchant.tax_code or "VAT15",
                products=products, buyers=buyers, **extra)


@router.get("/pos", response_class=HTMLResponse)
def pos_page(request: Request, db: Session = Depends(get_session)):  # NB: don't name this "pos" — it would shadow the app.pos module used below
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    return templates.TemplateResponse(request, "pos.html", _pos_ctx(request, merchant, db))


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
    try:
        doc = pos.checkout_sale(
            db, merchant, lines,
            payment_method=payment_method, buyer_tin=buyer_tin, buyer_name=buyer_name,
        )
    except Exception as exc:  # RegistrationError, missing secrets (KeyError), transport, …
        return templates.TemplateResponse(
            request, "pos.html",
            _pos_ctx(request, merchant, db, error=str(exc)),
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


@router.post("/receipt/{doc_id}/verify")
def receipt_verify(request: Request, doc_id: int, db: Session = Depends(get_session)):
    """Ask MoR live whether it knows this document (settles 'is it really registered?')."""
    merchant, doc = _load_doc(request, db, doc_id)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    if doc is None:
        return RedirectResponse(url="/app/receipts", status_code=303)
    # Payment receipts carry an RRN, not an IRN — MoR's verify endpoint works
    # on invoices/notes, so for an RCP we verify the invoice it pays.
    irn, via = doc.irn, ""
    if doc.doc_type == "RCP":
        try:
            inv_rows = (json.loads(doc.payload_json or "{}").get("Invoices")) or []
        except Exception:
            inv_rows = []
        irn = inv_rows[0].get("InvoiceIRN") if inv_rows else None
        via = "the invoice this receipt pays: "
        if not irn:
            return _back_to_doc(doc_id, err=(
                "This payment receipt has MoR's RRN and QR (issued at registration). "
                "MoR verifies by invoice IRN — open the linked invoice to run verify."
            ))
    if not irn:
        return _back_to_doc(doc_id, err="This document has no IRN to verify — it was never registered.")
    try:
        res = registration.verify_invoice_for_document(db, merchant, irn)
    except Exception as exc:
        return _back_to_doc(doc_id, err=f"Verify failed: {str(exc)[:250]}")
    if res.get("ok"):
        body = (res.get("mor") or {}).get("body") or {}
        dd = body.get("DocumentDetails") or {}
        return _back_to_doc(doc_id, ok=(
            f"MoR confirms {via}{dd.get('Type', doc.doc_type)} "
            f"#{dd.get('DocumentNumber', doc.document_number)} · {body.get('TransactionType', '')} "
            f"· registered {dd.get('Date', '')} — straight from MoR's database."
        ))
    return _back_to_doc(doc_id, err="MoR did not recognise this IRN.")


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
    try:
        cre, already = pos.refund_sale(db, merchant, doc, reason=reason)
    except ValueError as exc:
        return _back_to_doc(doc_id, err=str(exc))
    except Exception as exc:
        return _back_to_doc(doc_id, err=f"Refund failed: {str(exc)[:250]}")
    if already:
        return _back_to_doc(cre.id, ok="Already refunded — this is the credit note.")
    if cre.fiscal_status == FiscalStatus.REGISTERED:
        return _back_to_doc(cre.id, ok="Refund registered with MoR (credit note).")
    return _back_to_doc(cre.id, err=f"Credit note rejected: {(cre.error or '')[:250]}")


# --------------------------------------------------------------------------- #
# Z-report — day-close summary (Africa/Addis_Ababa day, UTC+3)
# --------------------------------------------------------------------------- #
@router.get("/zreport", response_class=HTMLResponse)
def zreport(request: Request, date: str = "", db: Session = Depends(get_session)):
    from datetime import timedelta

    from app import reports

    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date() if date else datetime.now(reports.ADDIS_TZ).date()
    except ValueError:
        day = datetime.now(reports.ADDIS_TZ).date()

    z = reports.zreport_for_day(db, merchant, day)

    return templates.TemplateResponse(request, "zreport.html", _ctx(
        request, merchant,
        day=day.strftime("%d %b %Y"), day_iso=day.isoformat(),
        prev_day=(day - timedelta(days=1)).isoformat(),
        next_day=(day + timedelta(days=1)).isoformat(),
        docs=z.docs, inv_count=z.inv_count, gross=z.gross, refunds=z.refunds,
        net=z.net, vat_out=z.vat_out,
        rcp_count=z.rcp_count,
        voided_count=z.voided_count, failed_count=z.failed_count,
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
# Items catalog (MoR-correct products: ItemCode, goods/service, per-item tax)
# --------------------------------------------------------------------------- #
def _back_to(path: str, *, ok: str = "", err: str = "") -> RedirectResponse:
    from urllib.parse import quote
    qs = f"?ok={quote(ok)}" if ok else (f"?err={quote(err)}" if err else "")
    return RedirectResponse(url=f"{path}{qs}", status_code=303)


def _clean_code(code: str, fallback: str) -> str:
    raw = (code or fallback or "ITEM").upper()
    return ("".join(ch for ch in raw if ch.isalnum() or ch == "-") or "ITEM")[:15]


@router.get("/products", response_class=HTMLResponse)
def products_page(request: Request, ok: str = "", err: str = "", db: Session = Depends(get_session)):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    items = list(db.execute(
        select(Product).where(Product.merchant_id == merchant.id)
        .order_by(Product.active.desc(), Product.name.asc())
    ).scalars())
    return templates.TemplateResponse(request, "products.html", _ctx(
        request, merchant, products=items, ok=ok or None, err=err or None,
    ))


@router.post("/products")
def product_create(
    request: Request,
    name: str = Form(...),
    code: str = Form(""),
    price: str = Form(...),
    nature: str = Form("goods"),
    tax_code: str = Form(""),
    stock: str = Form(""),
    db: Session = Depends(get_session),
):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    try:
        unit_price = round(float(price), 2)
        if unit_price <= 0:
            raise ValueError
    except ValueError:
        return _back_to("/app/products", err="Price must be a positive number.")
    code = _clean_code(code, name)
    exists = db.execute(select(Product.id).where(
        Product.merchant_id == merchant.id, func.upper(Product.code) == code)).scalar_one_or_none()
    if exists is not None:
        return _back_to("/app/products", err=f"Item code {code} already exists.")
    db.add(Product(
        merchant_id=merchant.id, code=code, name=name.strip()[:300],
        nature=(nature if nature in ("goods", "service") else "goods"),
        tax_code=(tax_code if tax_code in ("VAT15", "VAT0", "VATEX") else None),
        unit_price=unit_price,
        stock_qty=(float(stock) if stock.strip() else None),
    ))
    db.commit()
    return _back_to("/app/products", ok=f"{name.strip()} added to the catalog.")


@router.post("/products/{pid}/update")
def product_update(
    request: Request,
    pid: int,
    price: str = Form(""),
    stock: str = Form(""),
    db: Session = Depends(get_session),
):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    p = db.get(Product, pid)
    if p is None or p.merchant_id != merchant.id:
        return _back_to("/app/products", err="Item not found.")
    try:
        if price.strip():
            new_price = round(float(price), 2)
            if new_price <= 0:
                raise ValueError
            p.unit_price = new_price
        p.stock_qty = float(stock) if stock.strip() else None
    except ValueError:
        return _back_to("/app/products", err="Price and stock must be numbers.")
    db.commit()
    return _back_to("/app/products", ok=f"{p.name} updated.")


@router.post("/products/{pid}/toggle")
def product_toggle(request: Request, pid: int, db: Session = Depends(get_session)):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    p = db.get(Product, pid)
    if p is None or p.merchant_id != merchant.id:
        return _back_to("/app/products", err="Item not found.")
    p.active = not p.active
    db.commit()
    return _back_to("/app/products", ok=f"{p.name} {'restored to' if p.active else 'hidden from'} the POS.")


# --------------------------------------------------------------------------- #
# Buyer directory (B2B TINs; proven = a MoR registration succeeded with it)
# --------------------------------------------------------------------------- #
@router.get("/buyers", response_class=HTMLResponse)
def buyers_page(request: Request, ok: str = "", err: str = "", db: Session = Depends(get_session)):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    rows = list(db.execute(
        select(Buyer).where(Buyer.merchant_id == merchant.id)
        .order_by(Buyer.proven.desc(), Buyer.last_used_at.desc().nullslast(), Buyer.name.asc())
    ).scalars())
    return templates.TemplateResponse(request, "buyers.html", _ctx(
        request, merchant, buyers=rows, ok=ok or None, err=err or None,
    ))


@router.post("/buyers")
def buyer_create(
    request: Request,
    name: str = Form(...),
    tin: str = Form(...),
    db: Session = Depends(get_session),
):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    tin = "".join(ch for ch in tin if ch.isdigit())
    if len(tin) != 10:
        return _back_to("/app/buyers", err="Buyer TIN must be exactly 10 digits.")
    exists = db.execute(select(Buyer.id).where(
        Buyer.merchant_id == merchant.id, Buyer.tin == tin)).scalar_one_or_none()
    if exists is not None:
        return _back_to("/app/buyers", err="This TIN is already in the directory.")
    db.add(Buyer(merchant_id=merchant.id, name=name.strip()[:255] or "Customer", tin=tin))
    db.commit()
    return _back_to("/app/buyers", ok=f"{name.strip()} saved. The MoR-proven badge appears after the first successful sale.")


@router.post("/buyers/{bid}/delete")
def buyer_delete(request: Request, bid: int, db: Session = Depends(get_session)):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    b = db.get(Buyer, bid)
    if b is None or b.merchant_id != merchant.id:
        return _back_to("/app/buyers", err="Buyer not found.")
    db.delete(b)
    db.commit()
    return _back_to("/app/buyers", ok="Buyer removed.")


# --------------------------------------------------------------------------- #
# Reports (date range + VAT position + CSV) and the MoR verify sweep
# --------------------------------------------------------------------------- #
def _parse_range(start: str, end: str) -> tuple[date, date]:
    """Default range: the current Addis month to date."""
    from app import reports
    today_local = datetime.now(reports.ADDIS_TZ).date()
    try:
        start_day = datetime.strptime(start, "%Y-%m-%d").date() if start else today_local.replace(day=1)
    except ValueError:
        start_day = today_local.replace(day=1)
    try:
        end_day = datetime.strptime(end, "%Y-%m-%d").date() if end else today_local
    except ValueError:
        end_day = today_local
    return start_day, end_day


@router.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request, start: str = "", end: str = "", db: Session = Depends(get_session)):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    from app import reports
    start_day, end_day = _parse_range(start, end)
    rr = reports.range_report(db, merchant, start_day, end_day)
    today_local = datetime.now(reports.ADDIS_TZ).date()
    first_this = today_local.replace(day=1)
    last_month_end = first_this - timedelta(days=1)
    return templates.TemplateResponse(request, "reports.html", _ctx(
        request, merchant, r=rr,
        start=rr.start_day.isoformat(), end=rr.end_day.isoformat(),
        this_month=(first_this.isoformat(), today_local.isoformat()),
        last_month=(last_month_end.replace(day=1).isoformat(), last_month_end.isoformat()),
        last7=((today_local - timedelta(days=6)).isoformat(), today_local.isoformat()),
    ))


@router.get("/reports.csv")
def reports_csv(request: Request, start: str = "", end: str = "", db: Session = Depends(get_session)):
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    import csv
    import io

    from app import reports
    start_day, end_day = _parse_range(start, end)
    rr = reports.range_report(db, merchant, start_day, end_day)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["date_addis", "time", "ref", "type", "doc_number", "status",
                "amount_etb", "vat_etb", "buyer_tin", "irn", "rrn"])
    for d in rr.docs:
        local = d.created_at.astimezone(reports.ADDIS_TZ) if d.created_at else None
        try:
            vat = float((json.loads(d.payload_json or "{}").get("ValueDetails") or {}).get("TaxValue") or 0)
        except Exception:
            vat = 0.0
        w.writerow([
            local.strftime("%Y-%m-%d") if local else "", local.strftime("%H:%M:%S") if local else "",
            d.transaction_ref, d.doc_type, d.document_number or "", d.fiscal_status.value,
            f"{float(d.amount or 0):.2f}", f"{vat:.2f}", d.buyer_tin or "", d.irn or "", d.rrn or "",
        ])
    fname = f"receipt-report-{rr.start_day.isoformat()}-to-{rr.end_day.isoformat()}.csv"
    return PlainTextResponse(out.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/verify-sweep")
def verify_sweep(request: Request, db: Session = Depends(get_session)):
    """Bulk trust check: ask MoR /v1/verify about the latest registered docs."""
    merchant = _current(request, db)
    if merchant is None:
        return RedirectResponse(url="/app/login", status_code=303)
    docs = list(db.execute(
        select(Document).where(
            Document.merchant_id == merchant.id,
            Document.doc_type.in_(["INV", "CRE", "DEB"]),
            Document.fiscal_status == FiscalStatus.REGISTERED,
            Document.irn.isnot(None),
        ).order_by(Document.created_at.desc()).limit(8)
    ).scalars())
    ok = bad = 0
    for d in docs:
        try:
            res = registration.verify_invoice_for_document(db, merchant, d.irn)
            ok += 1 if res.get("ok") else 0
            bad += 0 if res.get("ok") else 1
        except Exception:
            bad += 1
    return RedirectResponse(
        url=f"/app?swept={len(docs)}&sweep_ok={ok}&sweep_bad={bad}", status_code=303)


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
