"""Receipt mobile API — JSON endpoints for the React Native (Expo) POS app.

Mounted at ``/api/m``. Mirrors the server-rendered webapp flows (login → OTP →
sell → fiscal receipt) but speaks JSON with stateless bearer tokens so a phone
can talk to it without cookies.

Auth model (no schema changes):
  * ``POST /auth/login``  (phone)            -> short-lived *challenge* token
  * ``POST /auth/verify`` (challenge + code) -> long-lived *session* token
  Tokens are HMAC-SHA256 over ``SESSION_SECRET`` (same secret the webapp
  sessions use): ``<kind>.<merchant_id>.<expiry>.<sig>``. Nothing stored.

OTP is the same DEV STUB as the webapp (code shown to the client) until an SMS
gateway is wired — swap ``_issue_challenge`` when that lands.

Checkout is idempotent on the client-supplied ``client_ref`` (used as the MoR
``transaction_ref``), which is what makes the app's offline "contingency mode"
safe to replay: queued sales sync at-most-once per ref.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone  # noqa: F401 (timedelta: Addis day window)

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import mor_client, pos, registration, reports
from app.db import get_session
from app.models import Document, FiscalStatus, Merchant, MerchantSecret
from app.secrets_backend import get_secrets_backend
from app.webapp import _apply_settings, _find_merchant_by_phone, _norm_phone, share_token

router = APIRouter(prefix="/api/m", tags=["mobile"])

SESSION_TTL = 60 * 60 * 24 * 30      # 30 days
CHALLENGE_TTL = 60 * 10              # 10 minutes


# --------------------------------------------------------------------------- #
# Stateless tokens
# --------------------------------------------------------------------------- #
def _secret() -> bytes:
    return os.environ.get("SESSION_SECRET", "dev-only-change-me").encode()


def _sign(kind: str, mid: int, exp: int) -> str:
    msg = f"{kind}.{mid}.{exp}"
    sig = hmac.new(_secret(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}.{sig}"


def _parse(token: str, kind: str) -> int | None:
    try:
        t_kind, mid, exp, sig = (token or "").split(".")
        if t_kind != kind:
            return None
        if not hmac.compare_digest(
            sig, hmac.new(_secret(), f"{t_kind}.{mid}.{exp}".encode(), hashlib.sha256).hexdigest()
        ):
            return None
        if int(exp) < time.time():
            return None
        return int(mid)
    except (ValueError, AttributeError, TypeError):
        # TypeError: compare_digest refuses non-ASCII str — malformed header, not a 500
        return None


def current_merchant(
    authorization: str = Header(default=""),
    db: Session = Depends(get_session),
) -> Merchant:
    token = authorization.removeprefix("Bearer ").strip()
    mid = _parse(token, "sess")
    merchant = db.get(Merchant, mid) if mid else None
    if merchant is None:
        raise HTTPException(status_code=401, detail="Session expired — sign in again.")
    return merchant


def _issue_challenge(merchant: Merchant) -> dict:
    # DEV STUB: a real build texts a random code and does NOT return it.
    return {
        "challenge": _sign("otp", merchant.id, int(time.time()) + CHALLENGE_TTL),
        "dev_code": "000000",
        "masked_phone": ("•••••" + (merchant.phone or "")[-4:]) if merchant.phone else None,
    }


# --------------------------------------------------------------------------- #
# Serializers
# --------------------------------------------------------------------------- #
def _merchant_json(m: Merchant) -> dict:
    return {
        "id": m.id, "tin": m.tin, "legal_name": m.legal_name,
        "phone": m.phone, "vat_number": m.vat_number, "tax_code": m.tax_code or "VAT15",
        "price_vat_inclusive": bool(m.price_vat_inclusive),
        "region": m.region, "city": m.city, "wereda": m.wereda,
        "system_type": m.system_type, "system_number": m.system_number,
        "base_url": m.base_url, "status": m.status,
    }


def _doc_json(d: Document, *, detail: bool = False) -> dict:
    out = {
        "id": d.id, "doc_type": d.doc_type, "transaction_ref": d.transaction_ref,
        "document_number": d.document_number, "irn": d.irn, "rrn": d.rrn,
        # UPPERCASE on the wire — the app's status enums/colors key off this
        "fiscal_status": (d.fiscal_status.value if hasattr(d.fiscal_status, "value")
                          else str(d.fiscal_status)).upper(),
        "amount": float(d.amount or 0), "currency": d.currency or "ETB",
        "buyer_tin": d.buyer_tin, "error": d.error,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "registered_at": d.registered_at.isoformat() if d.registered_at else None,
        "ack_date": d.ack_date,
    }
    if detail:
        payload = {}
        try:
            payload = json.loads(d.payload_json) if d.payload_json else {}
        except ValueError:
            payload = {}
        vals = payload.get("ValueDetails") or {}
        out.update({
            "qr_b64": d.qr_b64,
            "items": [{
                "description": it.get("ProductDescription") or it.get("ItemCode") or "Item",
                "quantity": float(it.get("Quantity") or 1),
                "line_total": float(it.get("TotalLineAmount") or 0),
                "tax_code": it.get("TaxCode"),
                "unit": it.get("Unit") or "PCS",
            } for it in (payload.get("ItemList") or [])],
            "tax_value": float(vals.get("TaxValue") or 0),
            "net_value": float(vals.get("NetValue") or vals.get("TotalValue") or 0),
            "buyer": (payload.get("BuyerDetails") or {}).get("LegalName"),
            "share_path": f"/r/{d.id}/{share_token(d.id)}",
        })
    return out


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@router.post("/auth/login")
def login(payload: dict = Body(...), db: Session = Depends(get_session)) -> dict:
    merchant = _find_merchant_by_phone(db, str(payload.get("phone") or ""))
    if merchant is None:
        raise HTTPException(status_code=404, detail="No business found for that number or TIN.")
    return _issue_challenge(merchant)


@router.post("/auth/signup")
def signup(payload: dict = Body(...), db: Session = Depends(get_session)) -> dict:
    tin = "".join(ch for ch in str(payload.get("tin") or "") if ch.isdigit())
    legal_name = str(payload.get("legal_name") or "").strip()
    phone = _norm_phone(str(payload.get("phone") or ""))
    if len(tin) != 10:
        raise HTTPException(status_code=422, detail="TIN must be exactly 10 digits.")
    if not legal_name:
        raise HTTPException(status_code=422, detail="Business name is required.")
    if len(phone) < 9:
        raise HTTPException(status_code=422, detail="A valid phone number is required.")
    if db.execute(select(Merchant).where(Merchant.tin == tin)).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="A business with this TIN already exists — sign in instead.")
    merchant = Merchant(
        tin=tin, legal_name=legal_name, phone=phone,
        system_type="POS", tax_code="VAT15", price_vat_inclusive=True,
        base_url="https://core.mor.gov.et", tls_verify=False, status="active",
    )
    merchant.secret = MerchantSecret()
    db.add(merchant)
    db.commit()
    return _issue_challenge(merchant)


@router.post("/auth/verify")
def verify(payload: dict = Body(...), db: Session = Depends(get_session)) -> dict:
    mid = _parse(str(payload.get("challenge") or ""), "otp")
    if mid is None:
        raise HTTPException(status_code=401, detail="Challenge expired — start again.")
    code = str(payload.get("code") or "").strip()
    # DEV STUB: accept the dev code or any 6 digits (matches webapp behaviour).
    if not (code.isdigit() and len(code) == 6):
        raise HTTPException(status_code=401, detail="Wrong code — try again.")
    merchant = db.get(Merchant, mid)
    if merchant is None:
        raise HTTPException(status_code=404, detail="Business no longer exists.")
    return {
        "token": _sign("sess", merchant.id, int(time.time()) + SESSION_TTL),
        "merchant": _merchant_json(merchant),
    }


@router.get("/me")
def me(merchant: Merchant = Depends(current_merchant)) -> dict:
    return {"merchant": _merchant_json(merchant)}


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@router.get("/dashboard")
def dashboard(merchant: Merchant = Depends(current_merchant),
              db: Session = Depends(get_session)) -> dict:
    # "Today" is the merchant's day (Africa/Addis_Ababa, UTC+3) — same window
    # the Z-report closes, so the two screens always agree.
    addis = timezone(timedelta(hours=3))
    start = (datetime.now(addis).replace(hour=0, minute=0, second=0, microsecond=0)
             .astimezone(timezone.utc))
    today = list(db.execute(
        select(Document).where(Document.merchant_id == merchant.id, Document.created_at >= start)
        .order_by(Document.created_at.desc())
    ).scalars())
    inv = [d for d in today if d.doc_type == "INV" and d.fiscal_status == FiscalStatus.REGISTERED]

    def _vat_of(d: Document) -> float:
        try:
            return float((json.loads(d.payload_json or "{}").get("ValueDetails") or {}).get("TaxValue") or 0)
        except (ValueError, TypeError):
            return 0.0

    recent = list(db.execute(
        select(Document).where(Document.merchant_id == merchant.id)
        .order_by(Document.created_at.desc()).limit(10)
    ).scalars())
    attention = list(db.execute(
        select(Document).where(
            Document.merchant_id == merchant.id,
            Document.fiscal_status.in_([FiscalStatus.FAILED, FiscalStatus.PENDING]),
        ).order_by(Document.created_at.desc()).limit(6)
    ).scalars())
    return {
        "today": {
            "count": len(today),
            "sales": len(inv),
            "gross": round(sum(float(d.amount or 0) for d in inv), 2),
            "vat": round(sum(_vat_of(d) for d in inv), 2),
        },
        "recent": [_doc_json(d) for d in recent],
        "attention": [_doc_json(d) for d in attention],
        "merchant": _merchant_json(merchant),
    }


# --------------------------------------------------------------------------- #
# Checkout — register invoice (+ best-effort sales receipt) with MoR
# --------------------------------------------------------------------------- #
@router.post("/checkout")
def checkout(payload: dict = Body(...),
             merchant: Merchant = Depends(current_merchant),
             db: Session = Depends(get_session)) -> dict:
    lines = payload.get("lines") or []
    if not lines:
        raise HTTPException(status_code=422, detail="Cart is empty.")
    client_ref = str(payload.get("client_ref") or "").strip() or None
    if client_ref:
        if len(client_ref) > 64:
            raise HTTPException(status_code=422, detail="client_ref too long (max 64 characters).")
        if client_ref.upper().startswith(("RCP-", "CRE-", "DEB-")):
            # server-derived ref namespaces — a colliding client ref would make
            # registration's idempotency hand back the wrong document type
            raise HTTPException(status_code=422, detail="client_ref must not start with RCP-/CRE-/DEB-.")

    try:
        doc = pos.checkout_sale(
            db, merchant, lines,
            payment_method=str(payload.get("payment_method") or "CASH"),
            buyer_tin=str(payload.get("buyer_tin") or ""),
            buyer_name=str(payload.get("buyer_name") or ""),
            transaction_ref=client_ref,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:400])
    # NOTE: a replayed client_ref that idempotent-hits an earlier FAILED doc is
    # returned as-is (status FAILED) — deliberately NOT auto-re-driven here. A
    # Failed-on-transport doc may in fact be REGISTERED at MoR (response lost),
    # and MoR has no idempotency key, so a server-side replay could double-
    # register the sale. The app parks the sale with the error; an explicit
    # user retry mints a FRESH ref (rebuilding the payload with current seller
    # data), and ops can re-drive transport failures via admin /retry.
    receipt_doc = db.execute(
        select(Document).where(Document.merchant_id == merchant.id,
                               Document.transaction_ref == f"RCP-{doc.transaction_ref}")
    ).scalar_one_or_none()
    return {
        "doc": _doc_json(doc, detail=True),
        "receipt": _doc_json(receipt_doc, detail=True) if receipt_doc is not None else None,
    }


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #
@router.get("/documents")
def documents(q: str = "", limit: int = 100,
              merchant: Merchant = Depends(current_merchant),
              db: Session = Depends(get_session)) -> dict:
    stmt = select(Document).where(Document.merchant_id == merchant.id)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(func.coalesce(Document.irn, "").ilike(like)
                          | func.coalesce(Document.transaction_ref, "").ilike(like))
    docs = list(db.execute(stmt.order_by(Document.created_at.desc())
                           .limit(max(1, min(limit, 200)))).scalars())
    return {"docs": [_doc_json(d) for d in docs]}


def _owned_doc(db: Session, merchant: Merchant, doc_id: int) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or doc.merchant_id != merchant.id:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


@router.get("/documents/{doc_id}")
def document_detail(doc_id: int,
                    merchant: Merchant = Depends(current_merchant),
                    db: Session = Depends(get_session)) -> dict:
    doc = _owned_doc(db, merchant, doc_id)
    payload = {}
    try:
        payload = json.loads(doc.payload_json) if doc.payload_json else {}
    except ValueError:
        payload = {}
    related = None
    if doc.doc_type == "RCP":
        inv_rows = payload.get("Invoices") or []
        irn = inv_rows[0].get("InvoiceIRN") if inv_rows else None
        if irn:
            related = db.execute(select(Document).where(
                Document.merchant_id == merchant.id, Document.irn == irn)).scalar_one_or_none()
    elif doc.doc_type in ("CRE", "DEB"):
        irn = (payload.get("ReferenceDetails") or {}).get("RelatedDocument")
        if irn:
            related = db.execute(select(Document).where(
                Document.merchant_id == merchant.id, Document.irn == irn)).scalar_one_or_none()
    children = []
    if doc.doc_type == "INV" and doc.irn:
        children = list(db.execute(
            select(Document)
            .where(Document.merchant_id == merchant.id, Document.id != doc.id,
                   func.coalesce(Document.payload_json, "").like(f"%{doc.irn}%"))
            .order_by(Document.created_at.desc()).limit(10)
        ).scalars())
    return {
        "doc": _doc_json(doc, detail=True),
        "related": _doc_json(related) if related is not None else None,
        "children": [_doc_json(c) for c in children],
    }


@router.post("/documents/{doc_id}/verify")
def document_verify(doc_id: int,
                    merchant: Merchant = Depends(current_merchant),
                    db: Session = Depends(get_session)) -> dict:
    doc = _owned_doc(db, merchant, doc_id)
    irn, via = doc.irn, ""
    if doc.doc_type == "RCP":
        try:
            inv_rows = (json.loads(doc.payload_json or "{}").get("Invoices")) or []
        except ValueError:
            inv_rows = []
        irn = inv_rows[0].get("InvoiceIRN") if inv_rows else None
        via = "the invoice this receipt pays: "
        if not irn:
            raise HTTPException(status_code=400, detail=(
                "This payment receipt has MoR's RRN and QR (issued at registration). "
                "MoR verifies by invoice IRN — open the linked invoice to run verify."
            ))
    if not irn:
        raise HTTPException(status_code=400, detail="No IRN to verify — this document was never registered.")
    try:
        res = registration.verify_invoice_for_document(db, merchant, irn)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Verify failed: {str(exc)[:250]}")
    if res.get("ok"):
        body = (res.get("mor") or {}).get("body") or {}
        dd = body.get("DocumentDetails") or {}
        return {"ok": True, "message": (
            f"MoR confirms {via}{dd.get('Type', doc.doc_type)} "
            f"#{dd.get('DocumentNumber', doc.document_number)} — registered {dd.get('Date', '')}, "
            "straight from MoR's database."
        )}
    return {"ok": False, "message": "MoR did not recognise this IRN."}


@router.post("/documents/{doc_id}/void")
def document_void(doc_id: int, payload: dict | None = Body(None),
                  merchant: Merchant = Depends(current_merchant),
                  db: Session = Depends(get_session)) -> dict:
    doc = _owned_doc(db, merchant, doc_id)
    if doc.doc_type not in ("INV", "CRE", "DEB") or not doc.irn:
        raise HTTPException(status_code=400, detail="Only registered invoices/notes can be voided.")
    payload = payload or {}
    try:
        registration.cancel_invoice_for_document(
            db, merchant, doc.irn,
            reason_code=str(payload.get("reason_code") or "3"),
            remark=str(payload.get("remark") or "").strip(),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Void failed: {str(exc)[:250]}")
    return {"ok": True, "message": "Voided — cancellation registered with MoR."}


@router.post("/documents/{doc_id}/refund")
def document_refund(doc_id: int, payload: dict | None = Body(None),
                    merchant: Merchant = Depends(current_merchant),
                    db: Session = Depends(get_session)) -> dict:
    doc = _owned_doc(db, merchant, doc_id)
    reason = str((payload or {}).get("reason") or "")
    try:
        cre, already = pos.refund_sale(db, merchant, doc, reason=reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Refund failed: {str(exc)[:250]}")
    if already:
        return {"ok": True, "doc_id": cre.id, "message": "Already refunded — this is the credit note."}
    if cre.fiscal_status == FiscalStatus.REGISTERED:
        return {"ok": True, "doc_id": cre.id, "message": "Refund registered with MoR (credit note)."}
    raise HTTPException(status_code=502, detail=f"Credit note rejected: {(cre.error or '')[:250]}")


# --------------------------------------------------------------------------- #
# Z-report (Africa/Addis_Ababa day, UTC+3)
# --------------------------------------------------------------------------- #
@router.get("/zreport")
def zreport(date: str = "",
            merchant: Merchant = Depends(current_merchant),
            db: Session = Depends(get_session)) -> dict:
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date() if date else None
    except ValueError:
        day = None
    z = reports.zreport_for_day(db, merchant, day)
    return {
        "day": z.day.isoformat(),
        "inv_count": z.inv_count,
        "gross": round(z.gross, 2),
        "refunds": round(z.refunds, 2),
        "net": round(z.net, 2),
        "vat_out": round(z.vat_out, 2),
        "rcp_count": z.rcp_count,
        "voided_count": z.voided_count,
        "failed_count": z.failed_count,
        "docs": [_doc_json(d) for d in z.docs],
    }


# --------------------------------------------------------------------------- #
# Settings — EIRMS credentials, INSA key/cert, seller record
# --------------------------------------------------------------------------- #
def _settings_json(merchant: Merchant) -> dict:
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
    return {
        "merchant": _merchant_json(merchant),
        "secrets": {
            "client_id": bool(sec and sec.client_id),
            "client_secret": bool(sec and sec.client_secret),
            "api_key": bool(sec and sec.api_key),
            "private_key": bool(key_ref and os.path.isfile(key_ref)),
            "certificate": cert_present,
            "cert_note": cert_note,
        },
    }


@router.get("/settings")
def settings_get(merchant: Merchant = Depends(current_merchant)) -> dict:
    return _settings_json(merchant)


def _form_from_payload(payload: dict, merchant: Merchant) -> dict:
    """Translate a JSON settings payload into ``_apply_settings`` form semantics.

    Empty/None values are dropped entirely — a mobile client has no "clear this
    field" UX, and present-but-blank seller fields would NULL the stored record
    (the historical wipe that broke MoR registration). ``tls_verify`` needs
    special care: ``_apply_settings`` applies HTML-checkbox semantics whenever
    ``legal_name`` is in the form, so an omitted key would silently force it
    False — pin it to the stored value unless the client explicitly sent one.
    """
    form = {}
    for k, v in payload.items():
        if k == "tls_verify" or v is None:
            continue
        s = str(v).strip()
        if s:
            form[k] = s
    tv = payload.get("tls_verify")
    if tv is None:                       # absent OR json null = keep stored
        tv = merchant.tls_verify
    tv_flag = "1" if tv in (True, 1, "1", "true", "True", "on") else ""
    if "legal_name" in form:
        form["tls_verify"] = tv_flag
    elif payload.get("tls_verify") is not None:
        # honour an explicit tls_verify even without legal_name: _apply_settings
        # only writes it inside its "full form" branch, so trigger that branch
        # with the unchanged stored legal name
        form["legal_name"] = merchant.legal_name or ""
        form["tls_verify"] = tv_flag
    return form


@router.post("/settings")
def settings_save(payload: dict = Body(...),
                  merchant: Merchant = Depends(current_merchant),
                  db: Session = Depends(get_session)) -> dict:
    _apply_settings(None, merchant, db, _form_from_payload(payload, merchant))
    return {"ok": True, **_settings_json(merchant)}


@router.post("/settings/test")
def settings_test(payload: dict | None = Body(None),
                  merchant: Merchant = Depends(current_merchant),
                  db: Session = Depends(get_session)) -> dict:
    if payload:
        _apply_settings(None, merchant, db, _form_from_payload(payload, merchant))
    try:
        secrets = get_secrets_backend().load_merchant_credentials(merchant)
        missing = [k for k in ("client_id", "client_secret", "api_key", "private_key", "certificate")
                   if not secrets.get(k)]
        if missing:
            raise RuntimeError("Missing: " + ", ".join(missing))
        token = mor_client.login(merchant, secrets)
        return {"ok": True, "message": f"Connected to MoR — login OK (token {token[:10]}…)."}
    except Exception as exc:
        return {"ok": False, "message": f"Connection test failed: {str(exc)[:400]}"}
