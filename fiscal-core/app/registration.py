"""Registration / lifecycle service — orchestrates builders + transport + DB.

This is the only layer that ties together the PURE builders
(:mod:`app.invoice_builder`, :mod:`app.note_builder`,
:mod:`app.receipt_builder`), the sync transport (:mod:`app.mor_client`), the
secrets backend (:mod:`app.secrets_backend`), and the multi-tenant data model
(:mod:`app.models`). Each merchant's invoice chain is serialized by the Postgres
advisory lock (:mod:`app.locks`, spec §6) and advanced **only on success**.

Design rules folded in from MOR_EIMS_CONTRACT.md:

  * **Idempotent on (merchant, transaction_ref)** — a transaction_ref gets at
    most one IRN. A re-submit returns the existing document untouched (§6).
  * **Advance chain only on success** — on ``statusCode == 200`` persist the
    MoR ``body`` fields (irn, documentNumber, ackDate, signedQR -> qr_b64,
    signedInvoice) and bump ``InvoiceChain`` (counter + last_irn). Otherwise the
    document is marked ``Failed`` with the error and the chain is untouched (§2).
  * **Cancel persists MoR's returned ``cancelationDate``** (NOT local time),
    guards an already-cancelled doc (§3 / do-not-inherit #7).
  * **Receipts/notes guard against a cancelled invoice** (§5 / do-not-inherit
    #5). Receipt success reads ``body.rrn`` (do-not-inherit #3).
  * **Notes** (CRE/DEB) are chained through ``/v1/register`` with their own IRN
    + counter; ``RelatedDocument`` = original invoice's IRN string (§4).

All MoR-facing functions are SYNC (mirroring the validated Delta code) and are
meant to be called from FastAPI ``def`` route handlers (threadpool), never from
the event loop.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import mor_client
from app.crypto import canonical
from app.invoice_builder import build_invoice
from app.locks import merchant_chain_lock
from app.models import Document, FiscalStatus, InvoiceChain, Merchant
from app.note_builder import build_credit_note, build_debit_note
from app.receipt_builder import build_sales_receipt
from app.secrets_backend import SecretsBackend, get_secrets_backend

logger = logging.getLogger("receipt.registration")

__all__ = [
    "RegistrationError",
    "MerchantNotFound",
    "DocumentNotFound",
    "InvoiceCancelled",
    "get_merchant_by_tin",
    "register_invoice_for_merchant",
    "cancel_invoice_for_document",
    "verify_invoice_for_document",
    "register_receipt_for_document",
    "issue_credit_note",
    "issue_debit_note",
    "retry_failed",
    "reconciliation",
]


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class RegistrationError(Exception):
    """Base error for the registration service (caller maps to HTTP 4xx/5xx)."""


class MerchantNotFound(RegistrationError):
    """No merchant exists for the given TIN."""


class DocumentNotFound(RegistrationError):
    """No matching fiscal document exists (by IRN / transaction_ref)."""


class InvoiceCancelled(RegistrationError):
    """Operation refused because the target invoice is cancelled (§5/§7.5)."""


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _status_ok(resp: Any) -> bool:
    """MoR success: ``statusCode == 200`` (or ``status == "success"``, §3)."""
    if not isinstance(resp, Mapping):
        return False
    if resp.get("statusCode") == 200:
        return True
    return str(resp.get("status", "")).lower() == "success"


def _body(resp: Any) -> dict:
    if isinstance(resp, Mapping):
        return dict(resp.get("body") or {})
    return {}


def _error_message(resp: Any) -> str:
    """Compact rejection message: ``<message>: <body excerpt>`` (matches Delta)."""
    if not isinstance(resp, Mapping):
        return str(resp)[:1000]
    msg = resp.get("message") or resp.get("status") or "EIMS rejected the request"
    try:
        body_excerpt = json.dumps(resp.get("body"))[:800]
    except (TypeError, ValueError):
        body_excerpt = str(resp.get("body"))[:800]
    return f"{msg}: {body_excerpt}"


def get_merchant_by_tin(session: Session, tin: str) -> Merchant:
    """Load a merchant by TIN or raise :class:`MerchantNotFound`."""
    merchant = session.execute(
        select(Merchant).where(Merchant.tin == str(tin))
    ).scalar_one_or_none()
    if merchant is None:
        raise MerchantNotFound(f"No merchant with TIN {tin!r}.")
    return merchant


def _load_secrets(merchant: Merchant, backend: Optional[SecretsBackend]) -> dict:
    backend = backend or get_secrets_backend()
    return backend.load_merchant_credentials(merchant)


def _get_or_create_chain(session: Session, merchant_id: int) -> InvoiceChain:
    """Return the merchant's chain head, creating it (counter=0) if absent.

    Must be called inside the advisory-locked region so only one writer races to
    create the row.
    """
    chain = session.get(InvoiceChain, merchant_id)
    if chain is None:
        chain = InvoiceChain(merchant_id=merchant_id, counter=0, last_irn=None)
        session.add(chain)
        session.flush()
    return chain


def _existing_document(
    session: Session, merchant_id: int, transaction_ref: str
) -> Optional[Document]:
    return session.execute(
        select(Document).where(
            Document.merchant_id == merchant_id,
            Document.transaction_ref == str(transaction_ref),
        )
    ).scalar_one_or_none()


def _items_payload(items: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Normalize API item dicts (snake_case) for the pure builders."""
    out: list[dict] = []
    for it in items:
        out.append({
            "nature_of_supplies": it.get("nature_of_supplies") or "service",
            "item_code": it.get("item_code"),
            "product_description": it.get("product_description"),
            "unit": it.get("unit") or "PCS",
            "unit_price": it.get("unit_price"),
            "quantity": it.get("quantity", 1),
            "discount": it.get("discount", 0),
            "tax_code": it.get("tax_code"),
        })
    return out


def _apply_success(
    doc: Document,
    chain: InvoiceChain,
    body: Mapping[str, Any],
    *,
    next_counter: int,
    fallback_document_number: str,
) -> None:
    """Persist a successful register: set doc fields + advance the chain (§2)."""
    irn = body.get("irn")
    doc.irn = irn
    doc.document_number = body.get("documentNumber") or fallback_document_number
    doc.ack_date = body.get("ackDate")
    doc.qr_b64 = body.get("signedQR")
    doc.signed_invoice = body.get("signedInvoice")
    doc.fiscal_status = FiscalStatus.REGISTERED
    doc.error = None
    doc.registered_at = _now()
    # Advance the per-merchant chain ONLY on success.
    chain.counter = next_counter
    chain.last_irn = irn


# --------------------------------------------------------------------------- #
# Register invoice (spec §2)
# --------------------------------------------------------------------------- #
def register_invoice_for_merchant(
    session: Session,
    merchant: Merchant,
    tx: Mapping[str, Any],
    *,
    secrets_backend: Optional[SecretsBackend] = None,
) -> Document:
    """Register a fiscal invoice for ``merchant``; idempotent per transaction_ref.

    Under the per-merchant advisory lock (spec §6): read the chain head, build
    the invoice with ``previous_irn = chain.last_irn`` and ``counter + 1``, call
    :func:`app.mor_client.register_invoice`, and on ``statusCode == 200`` persist
    the MoR ``body`` (irn, documentNumber, ackDate, signedQR -> qr_b64,
    signedInvoice) and advance the chain — else mark the document ``Failed``.

    Args:
        session: an open DB session. This function commits exactly once at the
            end of the locked region (so the advisory lock spans the chain write).
        merchant: the tenant (``app.models.Merchant``).
        tx: the transaction request, a mapping with::

                transaction_ref : str   (idempotency key, REQUIRED)
                items           : [ {item_code, product_description, unit_price,
                                      quantity?, discount?, nature_of_supplies?,
                                      unit?, tax_code?}, ... ]   (REQUIRED, >=1)
                buyer           : {legal_name?, email?, phone?, id_type?,
                                   id_number?, tin?}             (optional; tin -> B2B)
                amount          : float  (optional single-line total override)
                currency        : str    (default "ETB")
                exchange_rate   : float  (required by builder when currency != ETB)
                payment_mode    : str    (CASH/ADVANCE/CREDIT; default CASH)

        secrets_backend: optional backend override (tests). Defaults to the
            configured backend.

    Returns:
        The persisted :class:`app.models.Document` (Registered or Failed). A
        re-submit of an existing ``transaction_ref`` returns the existing doc
        unchanged (idempotency, §6).
    """
    transaction_ref = str(tx["transaction_ref"])
    items = _items_payload(tx["items"])
    buyer = tx.get("buyer")
    amount = tx.get("amount")
    currency = tx.get("currency") or "ETB"
    exchange_rate = tx.get("exchange_rate")
    payment_mode = tx.get("payment_mode")
    buyer_tin = (buyer or {}).get("tin") if buyer else None

    secrets = _load_secrets(merchant, secrets_backend)

    with merchant_chain_lock(session, merchant.tin):
        # Idempotency: at most one IRN per (merchant, transaction_ref) (§6).
        existing = _existing_document(session, merchant.id, transaction_ref)
        if existing is not None:
            logger.info(
                "register.idempotent_hit merchant_tin=%s tx=%s status=%s",
                merchant.tin, transaction_ref, existing.fiscal_status.value,
            )
            return existing

        chain = _get_or_create_chain(session, merchant.id)
        next_counter = int(chain.counter) + 1
        previous_irn = chain.last_irn  # JSON null on first invoice (builder handles).

        doc = Document(
            merchant_id=merchant.id,
            doc_type="INV",
            transaction_ref=transaction_ref,
            document_number=str(next_counter),
            fiscal_status=FiscalStatus.PENDING,
            amount=Decimal(str(amount)) if amount is not None else None,
            currency=(currency or "ETB").upper(),
            buyer_tin=str(buyer_tin) if buyer_tin else None,
        )
        session.add(doc)
        session.flush()  # reserve the (merchant, transaction_ref) unique row.

        try:
            invoice = build_invoice(
                merchant,
                document_number=str(next_counter),
                invoice_counter=next_counter,
                previous_irn=previous_irn,
                buyer=buyer,
                items_or_single=items,
                amount=amount,
                currency=currency,
                payment_method=payment_mode,
                exchange_rate=exchange_rate,
            )
            doc.payload_json = canonical(invoice)
            resp = mor_client.register_invoice(
                merchant, secrets, invoice, encrypt=bool(getattr(merchant, "encrypt_payload", False))
            )
        except Exception as exc:  # build error OR transport error.
            logger.error(
                "register.exception merchant_tin=%s tx=%s error=%s",
                merchant.tin, transaction_ref, exc,
            )
            doc.fiscal_status = FiscalStatus.FAILED
            doc.error = str(exc)[:1000]
            doc.retry_count = int(doc.retry_count or 0)
            session.commit()
            return doc

        if _status_ok(resp):
            _apply_success(
                doc, chain, _body(resp),
                next_counter=next_counter,
                fallback_document_number=str(next_counter),
            )
            session.commit()
            logger.info(
                "register.ok merchant_tin=%s tx=%s irn=%s counter=%s",
                merchant.tin, transaction_ref, doc.irn, next_counter,
            )
            return doc

        # Rejected -> Failed, chain NOT advanced.
        doc.fiscal_status = FiscalStatus.FAILED
        doc.error = _error_message(resp)[:1000]
        session.commit()
        logger.error(
            "register.rejected merchant_tin=%s tx=%s error=%s",
            merchant.tin, transaction_ref, doc.error,
        )
        return doc


# --------------------------------------------------------------------------- #
# Cancel (spec §3)
# --------------------------------------------------------------------------- #
def cancel_invoice_for_document(
    session: Session,
    merchant: Merchant,
    irn: str,
    *,
    reason_code: str = "3",
    remark: str = "",
    secrets_backend: Optional[SecretsBackend] = None,
) -> Document:
    """Cancel a registered invoice by IRN and persist MoR's ``cancelationDate``.

    Guards an already-cancelled document (returns it unchanged). On success
    (``statusCode == 200`` or ``status == "success"``) persists MoR's returned
    ``cancelationDate`` (NOT local time, do-not-inherit #7) and flags the
    document ``Cancelled``. ``reason_code`` is validated to {1,2,3,4} by the
    transport layer.

    Raises:
        DocumentNotFound: no document with that IRN for the merchant.
        RegistrationError: MoR rejected the cancel.
    """
    doc = session.execute(
        select(Document).where(
            Document.merchant_id == merchant.id, Document.irn == str(irn)
        )
    ).scalar_one_or_none()
    if doc is None:
        raise DocumentNotFound(f"No document with IRN {irn!r} for merchant {merchant.tin}.")

    if doc.fiscal_status == FiscalStatus.CANCELLED:
        logger.info("cancel.already merchant_tin=%s irn=%s", merchant.tin, irn)
        return doc

    secrets = _load_secrets(merchant, secrets_backend)
    resp = mor_client.cancel_invoice(merchant, secrets, str(irn), reason_code, remark or "")

    if _status_ok(resp):
        body = _body(resp)
        # Persist MoR's returned cancelationDate (spec §3 / do-not-inherit #7).
        doc.cancelation_date = body.get("cancelationDate") or body.get("cancellationDate")
        doc.fiscal_status = FiscalStatus.CANCELLED
        doc.error = None
        session.commit()
        logger.info(
            "cancel.ok merchant_tin=%s irn=%s cancelationDate=%s",
            merchant.tin, irn, doc.cancelation_date,
        )
        return doc

    msg = _error_message(resp)
    logger.error("cancel.rejected merchant_tin=%s irn=%s error=%s", merchant.tin, irn, msg)
    raise RegistrationError(msg)


# --------------------------------------------------------------------------- #
# Verify (spec §3)
# --------------------------------------------------------------------------- #
def verify_invoice_for_document(
    session: Session,
    merchant: Merchant,
    irn: str,
    *,
    secrets_backend: Optional[SecretsBackend] = None,
) -> dict:
    """Verify an invoice by IRN at MoR; return the parsed MoR response.

    Read-only at MoR (lowercase ``irn`` on the wire, §3). Does not mutate local
    state. The local document (if any) is included under ``"local"`` for
    convenience.
    """
    secrets = _load_secrets(merchant, secrets_backend)
    resp = mor_client.verify_invoice(merchant, secrets, str(irn))

    local = session.execute(
        select(Document).where(
            Document.merchant_id == merchant.id, Document.irn == str(irn)
        )
    ).scalar_one_or_none()

    return {
        "ok": _status_ok(resp),
        "irn": str(irn),
        "mor": resp,
        "local": {
            "fiscal_status": local.fiscal_status.value if local else None,
            "document_number": local.document_number if local else None,
            "cancelation_date": local.cancelation_date if local else None,
        } if local else None,
    }


# --------------------------------------------------------------------------- #
# Sales receipt (spec §5) — guard against cancelled invoice; read body.rrn
# --------------------------------------------------------------------------- #
def register_receipt_for_document(
    session: Session,
    merchant: Merchant,
    rcpt: Mapping[str, Any],
    *,
    secrets_backend: Optional[SecretsBackend] = None,
) -> Document:
    """Register a sales receipt; idempotent per transaction_ref. Reads body.rrn.

    Guards every covered invoice against a **cancelled** status
    (do-not-inherit #5) before sending. Not chained (no chain advance). On
    success persists ``body.rrn`` and marks the receipt document ``Registered``.

    Args:
        rcpt: mapping with::

            transaction_ref     : str   (idempotency key, REQUIRED)
            collected_amount    : float (REQUIRED)
            invoices            : [ {invoice_irn|irn, invoice_paid_amount?,
                                     total_amount?, payment_coverage?}, ... ]  (>=1)
            receipt_type        : str   (default "Sales Receipts")
            reason              : str    (optional)
            currency            : str    (default "ETB")
            exchange_rate       : float  (required when currency != ETB)
            transaction_details : {mode_of_payment?, collector_name?,
                                   payment_service_provider?, account_number?,
                                   transaction_number?}

    Raises:
        InvoiceCancelled: a covered invoice is cancelled locally.
        DocumentNotFound: a covered invoice IRN is unknown to this merchant.
    """
    transaction_ref = str(rcpt["transaction_ref"])

    # Idempotency by (merchant, transaction_ref).
    existing = _existing_document(session, merchant.id, transaction_ref)
    if existing is not None:
        logger.info("receipt.idempotent_hit merchant_tin=%s tx=%s", merchant.tin, transaction_ref)
        return existing

    raw_invoices = list(rcpt.get("invoices") or [])
    if not raw_invoices:
        raise RegistrationError("A sales receipt needs at least one covered invoice.")

    # Normalize + guard each covered invoice against cancellation (§5).
    invoices: list[dict] = []
    for inv in raw_invoices:
        irn = inv.get("invoice_irn") or inv.get("irn")
        if not irn:
            raise RegistrationError("Each receipt invoice needs an 'invoice_irn'.")
        local = session.execute(
            select(Document).where(
                Document.merchant_id == merchant.id, Document.irn == str(irn)
            )
        ).scalar_one_or_none()
        if local is None:
            raise DocumentNotFound(
                f"No registered invoice with IRN {irn!r} for merchant {merchant.tin}."
            )
        if local.fiscal_status == FiscalStatus.CANCELLED:
            raise InvoiceCancelled(
                f"Cannot issue a receipt against cancelled invoice {irn!r}."
            )
        amount = inv.get("invoice_paid_amount")
        if amount is None:
            amount = inv.get("total_amount")
        if amount is None:
            amount = float(local.amount) if local.amount is not None else 0.0
        invoices.append({
            "irn": str(irn),
            "amount": float(amount),
            "payment_coverage": inv.get("payment_coverage") or "FULL",
            "invoice_paid_amount": inv.get("invoice_paid_amount", amount),
            "total_amount": inv.get("total_amount", amount),
        })

    secrets = _load_secrets(merchant, secrets_backend)
    collected_amount = float(rcpt["collected_amount"])
    currency = rcpt.get("currency") or "ETB"

    # Receipt counter: reuse the merchant's chain counter (receipts are not
    # chained but the schema wants a counter; matches Delta's behaviour).
    chain = session.get(InvoiceChain, merchant.id)
    receipt_counter = int(chain.counter) if chain else 0

    doc = Document(
        merchant_id=merchant.id,
        doc_type="RCP",
        transaction_ref=transaction_ref,
        fiscal_status=FiscalStatus.PENDING,
        amount=Decimal(str(collected_amount)),
        currency=(currency or "ETB").upper(),
    )
    session.add(doc)
    session.flush()

    try:
        receipt = build_sales_receipt(
            merchant,
            invoices=invoices,
            collected_amount=collected_amount,
            receipt_counter=receipt_counter,
            reason=rcpt.get("reason"),
            txn_details=rcpt.get("transaction_details"),
            receipt_number=rcpt.get("receipt_number") or f"REC-{transaction_ref}",
            receipt_type=rcpt.get("receipt_type") or "Sales Receipts",
            currency=currency,
            exchange_rate=rcpt.get("exchange_rate"),
        )
        doc.payload_json = canonical(receipt)
        resp = mor_client.register_receipt(merchant, secrets, receipt)
    except Exception as exc:
        logger.error("receipt.exception merchant_tin=%s tx=%s error=%s", merchant.tin, transaction_ref, exc)
        doc.fiscal_status = FiscalStatus.FAILED
        doc.error = str(exc)[:1000]
        session.commit()
        return doc

    if _status_ok(resp):
        body = _body(resp)
        doc.rrn = body.get("rrn")  # success reads body.rrn (do-not-inherit #3).
        doc.qr_b64 = body.get("signedQR") or body.get("qr")
        doc.fiscal_status = FiscalStatus.REGISTERED
        doc.error = None
        doc.registered_at = _now()
        session.commit()
        logger.info("receipt.ok merchant_tin=%s tx=%s rrn=%s", merchant.tin, transaction_ref, doc.rrn)
        return doc

    doc.fiscal_status = FiscalStatus.FAILED
    doc.error = _error_message(resp)[:1000]
    session.commit()
    logger.error("receipt.rejected merchant_tin=%s tx=%s error=%s", merchant.tin, transaction_ref, doc.error)
    return doc


# --------------------------------------------------------------------------- #
# Credit / Debit notes (spec §4) — chained via /v1/register, own IRN + counter
# --------------------------------------------------------------------------- #
def _issue_note(
    session: Session,
    merchant: Merchant,
    doc_type: str,
    note: Mapping[str, Any],
    secrets_backend: Optional[SecretsBackend],
) -> Document:
    """Shared CRE/DEB issuance (chained, idempotent, guards cancelled original)."""
    transaction_ref = str(note["transaction_ref"])
    related_irn = note.get("related_irn")
    if not related_irn:
        raise RegistrationError(f"{doc_type} note requires the original invoice's related_irn.")
    reason = note.get("reason")
    items = _items_payload(note["items"])
    buyer = note.get("buyer")
    amount = note.get("amount")
    currency = note.get("currency") or "ETB"
    exchange_rate = note.get("exchange_rate")
    payment_mode = note.get("payment_mode")

    secrets = _load_secrets(merchant, secrets_backend)

    with merchant_chain_lock(session, merchant.tin):
        existing = _existing_document(session, merchant.id, transaction_ref)
        if existing is not None:
            logger.info(
                "note.idempotent_hit merchant_tin=%s tx=%s type=%s",
                merchant.tin, transaction_ref, doc_type,
            )
            return existing

        # Guard: refuse a note against a cancelled original invoice (§5/§7.5).
        original = session.execute(
            select(Document).where(
                Document.merchant_id == merchant.id, Document.irn == str(related_irn)
            )
        ).scalar_one_or_none()
        if original is not None and original.fiscal_status == FiscalStatus.CANCELLED:
            raise InvoiceCancelled(
                f"Cannot issue a {doc_type} note against cancelled invoice {related_irn!r}."
            )
        original_total = (
            float(original.amount) if (original is not None and original.amount is not None) else None
        )

        chain = _get_or_create_chain(session, merchant.id)
        next_counter = int(chain.counter) + 1
        previous_irn = chain.last_irn

        doc = Document(
            merchant_id=merchant.id,
            doc_type=doc_type,
            transaction_ref=transaction_ref,
            document_number=str(next_counter),
            fiscal_status=FiscalStatus.PENDING,
            amount=Decimal(str(amount)) if amount is not None else None,
            currency=(currency or "ETB").upper(),
        )
        session.add(doc)
        session.flush()

        try:
            if doc_type == "CRE":
                payload = build_credit_note(
                    merchant,
                    document_number=str(next_counter),
                    invoice_counter=next_counter,
                    previous_irn=previous_irn,
                    related_irn=str(related_irn),
                    reason=reason or "Refund / return of service",
                    buyer=buyer,
                    items_or_single=items,
                    amount=amount,
                    currency=currency,
                    payment_method=payment_mode,
                    exchange_rate=exchange_rate,
                    original_total=original_total,
                )
            else:
                payload = build_debit_note(
                    merchant,
                    document_number=str(next_counter),
                    invoice_counter=next_counter,
                    previous_irn=previous_irn,
                    related_irn=str(related_irn),
                    reason=reason or "Additional charge",
                    buyer=buyer,
                    items_or_single=items,
                    amount=amount,
                    currency=currency,
                    payment_method=payment_mode,
                    exchange_rate=exchange_rate,
                )
            doc.payload_json = canonical(payload)
            resp = mor_client.register_invoice(
                merchant, secrets, payload,
                encrypt=bool(getattr(merchant, "encrypt_payload", False)),
            )
        except Exception as exc:
            logger.error(
                "note.exception merchant_tin=%s tx=%s type=%s error=%s",
                merchant.tin, transaction_ref, doc_type, exc,
            )
            doc.fiscal_status = FiscalStatus.FAILED
            doc.error = str(exc)[:1000]
            session.commit()
            return doc

        if _status_ok(resp):
            _apply_success(
                doc, chain, _body(resp),
                next_counter=next_counter,
                fallback_document_number=str(next_counter),
            )
            session.commit()
            logger.info(
                "note.ok merchant_tin=%s tx=%s type=%s irn=%s",
                merchant.tin, transaction_ref, doc_type, doc.irn,
            )
            return doc

        doc.fiscal_status = FiscalStatus.FAILED
        doc.error = _error_message(resp)[:1000]
        session.commit()
        logger.error(
            "note.rejected merchant_tin=%s tx=%s type=%s error=%s",
            merchant.tin, transaction_ref, doc_type, doc.error,
        )
        return doc


def issue_credit_note(
    session: Session,
    merchant: Merchant,
    note: Mapping[str, Any],
    *,
    secrets_backend: Optional[SecretsBackend] = None,
) -> Document:
    """Issue a credit note (CRE) chained off the original invoice (spec §4).

    ``note`` is like the register-invoice ``tx`` mapping plus ``related_irn``
    (the original invoice's IRN string) and ``reason`` (mandatory text). Enforces
    credit <= original (+0.005) when the original's amount is known, and refuses a
    note against a cancelled original. Returns the persisted Document.
    """
    return _issue_note(session, merchant, "CRE", note, secrets_backend)


def issue_debit_note(
    session: Session,
    merchant: Merchant,
    note: Mapping[str, Any],
    *,
    secrets_backend: Optional[SecretsBackend] = None,
) -> Document:
    """Issue a debit note (DEB) chained off the original invoice (spec §4).

    Same shape as :func:`issue_credit_note` (``related_irn`` + ``reason``), with
    no credit-ceiling guard. Returns the persisted Document.
    """
    return _issue_note(session, merchant, "DEB", note, secrets_backend)


# --------------------------------------------------------------------------- #
# Ops: retry failed + reconciliation
# --------------------------------------------------------------------------- #
def retry_failed(
    session: Session,
    *,
    limit: int = 50,
    merchant: Optional[Merchant] = None,
    secrets_backend: Optional[SecretsBackend] = None,
) -> dict:
    """Re-register Failed invoice/note documents (bounded), advancing the chain.

    Selects up to ``limit`` ``Failed`` INV/CRE/DEB documents (optionally scoped
    to one merchant), and re-runs registration **as a fresh chain attempt** under
    the per-merchant lock: a new counter/previous_irn is taken, the document is
    rebuilt from its stored inputs is NOT possible (we did not persist the raw
    inputs), so retry replays via the original transaction by re-issuing with the
    stored ``payload_json`` only when present.

    To keep this safe and idempotent we re-send the EXACT canonical payload that
    was attempted (``payload_json``) rather than rebuilding — the chain counter is
    advanced only on success. Documents with no stored payload are skipped (they
    failed before a payload was built, e.g. a validation error) and reported.

    Returns a summary ``{attempted, succeeded, failed, skipped, results:[...]}``.
    """
    stmt = (
        select(Document)
        .where(
            Document.fiscal_status == FiscalStatus.FAILED,
            Document.doc_type.in_(("INV", "CRE", "DEB")),
        )
        .order_by(Document.created_at.asc())
        .limit(int(limit))
    )
    if merchant is not None:
        stmt = stmt.where(Document.merchant_id == merchant.id)

    docs = list(session.execute(stmt).scalars())
    summary = {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0, "results": []}

    for doc in docs:
        summary["attempted"] += 1
        m = doc.merchant if doc.merchant is not None else session.get(Merchant, doc.merchant_id)
        if m is None:
            summary["skipped"] += 1
            summary["results"].append({"id": doc.id, "skipped": "merchant missing"})
            continue
        if not doc.payload_json:
            summary["skipped"] += 1
            summary["results"].append({"id": doc.id, "skipped": "no stored payload"})
            continue

        secrets = _load_secrets(m, secrets_backend)
        with merchant_chain_lock(session, m.tin):
            chain = _get_or_create_chain(session, m.id)
            next_counter = int(chain.counter) + 1
            try:
                payload = json.loads(doc.payload_json)
                # Refresh chain-dependent fields so the replay is consistent.
                payload.setdefault("SourceSystem", {})["InvoiceCounter"] = next_counter
                payload.setdefault("ReferenceDetails", {})["PreviousIrn"] = chain.last_irn or None
                if "DocumentDetails" in payload:
                    payload["DocumentDetails"]["DocumentNumber"] = str(next_counter)
                doc.payload_json = canonical(payload)
                resp = mor_client.register_invoice(
                    m, secrets, payload, encrypt=bool(getattr(m, "encrypt_payload", False))
                )
            except Exception as exc:
                doc.retry_count = int(doc.retry_count or 0) + 1
                doc.error = str(exc)[:1000]
                session.commit()
                summary["failed"] += 1
                summary["results"].append({"id": doc.id, "ok": False, "error": str(exc)})
                continue

            doc.retry_count = int(doc.retry_count or 0) + 1
            if _status_ok(resp):
                _apply_success(
                    doc, chain, _body(resp),
                    next_counter=next_counter,
                    fallback_document_number=str(next_counter),
                )
                session.commit()
                summary["succeeded"] += 1
                summary["results"].append({"id": doc.id, "ok": True, "irn": doc.irn})
            else:
                doc.error = _error_message(resp)[:1000]
                session.commit()
                summary["failed"] += 1
                summary["results"].append({"id": doc.id, "ok": False, "error": doc.error})

    logger.info(
        "retry_failed attempted=%s succeeded=%s failed=%s skipped=%s",
        summary["attempted"], summary["succeeded"], summary["failed"], summary["skipped"],
    )
    return summary


def reconciliation(
    session: Session,
    *,
    limit: int = 50,
    merchant: Optional[Merchant] = None,
    secrets_backend: Optional[SecretsBackend] = None,
) -> dict:
    """Reconcile locally-Registered documents against MoR's /v1/verify (read-only).

    For up to ``limit`` ``Registered`` documents that have an IRN (optionally for
    one merchant), call :func:`app.mor_client.verify_invoice` and report whether
    MoR agrees. Does NOT mutate local state — it surfaces drift for an operator.

    Returns ``{checked, in_sync, mismatched, errors, results:[...]}``.
    """
    stmt = (
        select(Document)
        .where(
            Document.fiscal_status == FiscalStatus.REGISTERED,
            Document.irn.is_not(None),
        )
        .order_by(Document.registered_at.desc().nullslast())
        .limit(int(limit))
    )
    if merchant is not None:
        stmt = stmt.where(Document.merchant_id == merchant.id)

    docs = list(session.execute(stmt).scalars())
    summary = {"checked": 0, "in_sync": 0, "mismatched": 0, "errors": 0, "results": []}

    for doc in docs:
        summary["checked"] += 1
        m = doc.merchant if doc.merchant is not None else session.get(Merchant, doc.merchant_id)
        if m is None:
            summary["errors"] += 1
            summary["results"].append({"id": doc.id, "error": "merchant missing"})
            continue
        secrets = _load_secrets(m, secrets_backend)
        try:
            resp = mor_client.verify_invoice(m, secrets, str(doc.irn))
        except Exception as exc:
            summary["errors"] += 1
            summary["results"].append({"id": doc.id, "irn": doc.irn, "error": str(exc)})
            continue
        if _status_ok(resp):
            summary["in_sync"] += 1
            summary["results"].append({"id": doc.id, "irn": doc.irn, "in_sync": True})
        else:
            summary["mismatched"] += 1
            summary["results"].append(
                {"id": doc.id, "irn": doc.irn, "in_sync": False, "mor": _error_message(resp)}
            )

    logger.info(
        "reconciliation checked=%s in_sync=%s mismatched=%s errors=%s",
        summary["checked"], summary["in_sync"], summary["mismatched"], summary["errors"],
    )
    return summary
