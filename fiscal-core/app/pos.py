"""Shared POS sale flow — one code path from cart lines to a registered sale.

Both sales channels (the web POS in :mod:`app.webapp` and the Telegram bot in
:mod:`app.telegram_bot`) call :func:`checkout_sale`, so the fiscally-critical
parts — line math, tax code, payment-mode mapping, buyer rules, and the
invoice → sales-receipt sequence — cannot drift between channels.

Semantics are exactly those of the original web checkout: register the invoice
(idempotent, chain-advancing), then issue the paying sales receipt best-effort
(an RCP failure never rolls back a registered invoice).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import registration
from app.locks import merchant_chain_lock
from app.models import Buyer, Document, FiscalStatus, Merchant, Product


def build_items(merchant: Merchant, lines: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Normalize cart lines (``{name, price, qty, code?, discount?, nature?, tax_code?}``).

    ``nature`` and ``tax_code`` are optional per-line overrides supplied by
    catalog-backed carts (spec §2: NatureOfSupplies is a lowercase enum, error
    7025; TaxCode is per ItemList line). Free-typed lines keep the old
    defaults: goods + the merchant's tax code.
    """
    return [{
        "item_code": (str(li.get("code") or li.get("name") or "ITEM"))[:15],
        "product_description": str(li.get("name") or "Item")[:300],
        "unit_price": float(li.get("price") or 0),
        "quantity": float(li.get("qty") or 1),
        "discount": float(li.get("discount") or 0),
        "nature_of_supplies": (li.get("nature") if li.get("nature") in ("goods", "service") else "goods"),
        "unit": "PCS",
        "tax_code": (str(li.get("tax_code")) if li.get("tax_code") in ("VAT15", "VAT0", "VATEX")
                     else (merchant.tax_code or "VAT15")),
    } for li in lines]


def sale_total(items: Sequence[Mapping[str, Any]]) -> float:
    return round(sum(i["unit_price"] * i["quantity"] - i["discount"] for i in items), 2)


def payment_mode(payment_method: str) -> str:
    """MoR knows CASH/CREDIT; Telebirr & other mobile money settle as CASH."""
    return "CASH" if (payment_method or "").upper() in ("CASH", "TELEBIRR", "MOBILE") else "CREDIT"


def checkout_sale(
    db: Session,
    merchant: Merchant,
    lines: Sequence[Mapping[str, Any]],
    *,
    payment_method: str = "CASH",
    buyer_tin: str = "",
    buyer_name: str = "",
    ref_prefix: str = "POS",
    transaction_ref: str | None = None,
) -> Document:
    """Register a sale: invoice with MoR, then the paying receipt (best-effort).

    Returns the invoice :class:`Document`; raises whatever
    :func:`registration.register_invoice_for_merchant` raises on failure.

    ``transaction_ref`` lets a channel supply its own ref (the mobile app's
    offline queue replays with a device-generated ref, making the sync
    at-most-once via registration's ``(merchant, transaction_ref)`` idempotency).
    """
    items = build_items(merchant, lines)
    total = sale_total(items)
    buyer_tin = (buyer_tin or "").strip()
    buyer_name = (buyer_name or "").strip()

    tx = {
        "transaction_ref": (transaction_ref or f"{ref_prefix}-{uuid.uuid4().hex[:12]}")[:64],
        "amount": total,
        "currency": "ETB",
        "payment_mode": payment_mode(payment_method),
        "items": items,
        "buyer": ({"legal_name": buyer_name, "tin": buyer_tin} if buyer_tin
                  else ({"legal_name": buyer_name} if buyer_name else None)),
    }

    # Snapshot pre-registration status so an idempotent replay (registration
    # returns the already-REGISTERED doc for this ref) never double-decrements
    # stock or re-touches the buyer directory.
    was_registered = db.execute(
        select(Document.fiscal_status).where(
            Document.merchant_id == merchant.id,
            Document.transaction_ref == tx["transaction_ref"],
        )
    ).scalar_one_or_none() == FiscalStatus.REGISTERED

    doc = registration.register_invoice_for_merchant(db, merchant, tx)

    if doc.fiscal_status == FiscalStatus.REGISTERED and not was_registered:
        _after_registered_sale(db, merchant, items, buyer_tin=buyer_tin, buyer_name=buyer_name)

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
    return doc


def _after_registered_sale(
    db: Session,
    merchant: Merchant,
    items: Sequence[Mapping[str, Any]],
    *,
    buyer_tin: str = "",
    buyer_name: str = "",
) -> None:
    """Post-success side effects shared by every sales channel.

    1. Decrement tracked stock for catalog items matched by ItemCode
       (untracked products — stock_qty NULL — are left alone; counts may go
       negative so oversell is visible instead of silently clamped).
    2. Upsert the buyer directory for B2B sales: a successful registration is
       proof the TIN exists in MoR's registry, so the row is marked proven.

    Best-effort by design: a failure here must never mask a registered sale
    (registration committed the fiscal document already), so errors roll back
    the side effects and are swallowed.
    """
    try:
        codes = {str(i.get("item_code") or "").upper(): float(i.get("quantity") or 0)
                 for i in items if i.get("item_code")}
        if codes:
            products = list(db.execute(
                select(Product).where(
                    Product.merchant_id == merchant.id,
                    func.upper(Product.code).in_(list(codes)),
                )
            ).scalars())
            for p in products:
                if p.stock_qty is not None:
                    p.stock_qty = float(p.stock_qty) - codes.get(p.code.upper(), 0)

        tin = (buyer_tin or "").strip()
        if tin:
            buyer = db.execute(
                select(Buyer).where(Buyer.merchant_id == merchant.id, Buyer.tin == tin)
            ).scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if buyer is None:
                db.add(Buyer(merchant_id=merchant.id, tin=tin,
                             name=(buyer_name or "Customer")[:255],
                             proven=True, last_used_at=now))
            else:
                buyer.proven = True
                buyer.last_used_at = now
                if buyer_name and buyer.name in ("", "Customer"):
                    buyer.name = buyer_name[:255]
        db.commit()
    except Exception:
        db.rollback()


def _note_references_irn(d: Document, irn: str) -> bool:
    """Does this credit note's payload point at ``irn`` as its related document?"""
    try:
        ref = (json.loads(d.payload_json or "{}").get("ReferenceDetails") or {}).get("RelatedDocument")
    except ValueError:
        return False
    return ref == irn


def refund_sale(db: Session, merchant: Merchant, doc: Document, *, reason: str = "") -> tuple[Document, bool]:
    """Refund a registered invoice in full via an MoR credit note.

    Returns ``(credit_note, already_refunded)``. Idempotency is bound to the
    invoice's IRN — a registered CRE whose ``ReferenceDetails.RelatedDocument``
    is this IRN counts as done. (Matching on the ``CRE-<ref>`` prefix alone is
    wrong: with client-supplied refs, refunding ``S-1`` would LIKE-match the
    unrelated ``CRE-S-10``.) Raises :class:`ValueError` for precondition
    failures, and whatever :func:`registration.issue_credit_note` raises.
    """
    if doc.doc_type != "INV" or doc.fiscal_status != FiscalStatus.REGISTERED or not doc.irn:
        raise ValueError("Refunds need a registered invoice.")
    if not doc.amount:
        raise ValueError("Original amount unknown — cannot refund.")

    # The dedupe check runs under the per-merchant chain lock (reentrant with
    # the one issue_credit_note takes): two concurrent refunds of the same
    # invoice serialize here, and the loser re-reads AFTER the winner's commit
    # released the lock — so it sees the fresh CRE and returns already=True
    # instead of minting a second suffixed ref past the ref-idempotency guard.
    with merchant_chain_lock(db, merchant.tin):
        # Any registered credit note referencing this IRN = already refunded.
        candidates = list(db.execute(
            select(Document).where(
                Document.merchant_id == merchant.id,
                Document.doc_type == "CRE",
                func.coalesce(Document.payload_json, "").like(f"%{doc.irn}%"),
            )
        ).scalars())
        done = next((c for c in candidates
                     if c.fiscal_status == FiscalStatus.REGISTERED and _note_references_irn(c, doc.irn)), None)
    if done is not None:
        return done, True

    # MoR rule 7020: a credit note's items must MIRROR the original invoice's
    # items (product/qty/tax code/unit) — rebuild them from the stored payload.
    # Feeding TotalLineAmount/qty back through the builder re-finds the exact
    # same UnitPrice, so the note reproduces the original lines to the cent.
    try:
        orig_items = (json.loads(doc.payload_json or "{}").get("ItemList")) or []
    except ValueError:
        orig_items = []
    if not orig_items:
        raise ValueError("Original items unavailable — cannot refund.")
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

    # Fresh ref: exact base if it's never been used by ANY document (a FAILED
    # attempt must not block the retry, and registration's ref-idempotency
    # must never hand us some other invoice's note), else a suffixed one.
    base_ref = f"CRE-{doc.transaction_ref}"[:64]
    ref_taken = db.execute(
        select(Document.id).where(Document.merchant_id == merchant.id,
                                  Document.transaction_ref == base_ref).limit(1)
    ).scalar_one_or_none() is not None
    ref = base_ref if not ref_taken else f"{base_ref[:57]}-{uuid.uuid4().hex[:6]}"

    # MoR 7030: the note's transaction type (B2B/B2C) must match the original —
    # carry the original invoice's buyer over to the credit note.
    try:
        orig_buyer = (json.loads(doc.payload_json or "{}").get("BuyerDetails")) or {}
    except ValueError:
        orig_buyer = {}
    buyer = None
    if orig_buyer.get("Tin"):
        buyer = {"legal_name": orig_buyer.get("LegalName") or "Customer", "tin": orig_buyer["Tin"]}

    cre = registration.issue_credit_note(db, merchant, {
        "transaction_ref": ref,
        "amount": float(doc.amount),
        "currency": doc.currency or "ETB",
        "payment_mode": "CASH",
        "related_irn": doc.irn,
        "reason": (reason.strip() or "Refund / return of goods")[:300],
        "items": items,
        "buyer": buyer,
    })
    return cre, False
