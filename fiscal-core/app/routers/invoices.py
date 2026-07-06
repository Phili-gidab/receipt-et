"""Fiscal document endpoints — register / cancel / verify / receipt / notes.

All handlers are sync ``def`` (threadpool) because the registration service and
MoR transport are synchronous. The service is idempotent per
(merchant, transaction_ref) and never raises on a MoR *rejection* — it returns a
``Failed`` document with the error — so a 200 here can still carry
``fiscal_status: "Failed"``. Exceptions are reserved for unknown merchant /
document / cancelled-invoice guards, which map to 4xx.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import registration
from app.db import get_session
from app.models import Document, Merchant
from app.schemas import (
    CancelReasonCode,
    FiscalDocumentResponse,
    ReceiptRequest,
    RegisterInvoiceRequest,
)

router = APIRouter(prefix="/merchants/{tin}", tags=["fiscal"])


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _merchant(session: Session, tin: str) -> Merchant:
    try:
        return registration.get_merchant_by_tin(session, tin)
    except registration.MerchantNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def _resp(doc: Document) -> FiscalDocumentResponse:
    """Build the response DTO explicitly (enum -> value, Decimal -> float)."""
    return FiscalDocumentResponse(
        id=doc.id,
        merchant_id=doc.merchant_id,
        doc_type=doc.doc_type,
        transaction_ref=doc.transaction_ref,
        document_number=doc.document_number,
        irn=doc.irn,
        rrn=doc.rrn,
        fiscal_status=doc.fiscal_status.value,
        qr_b64=doc.qr_b64,
        signed_invoice=doc.signed_invoice,
        ack_date=doc.ack_date,
        cancelation_date=doc.cancelation_date,
        error=doc.error,
        amount=float(doc.amount) if doc.amount is not None else None,
        currency=doc.currency,
        buyer_tin=doc.buyer_tin,
    )


def _tx_from(payload: RegisterInvoiceRequest) -> dict:
    return {
        "transaction_ref": payload.transaction_ref,
        "items": [i.model_dump() for i in payload.items],
        "buyer": payload.buyer.model_dump() if payload.buyer else None,
        "currency": payload.currency,
        "exchange_rate": payload.exchange_rate,
        "payment_mode": payload.payment_mode,
    }


# --------------------------------------------------------------------------- #
# Register invoice (spec §2)
# --------------------------------------------------------------------------- #
@router.post("/invoices", response_model=FiscalDocumentResponse)
def register_invoice(
    tin: str, payload: RegisterInvoiceRequest, session: Session = Depends(get_session)
) -> FiscalDocumentResponse:
    """Register a B2C/B2B invoice. Idempotent per ``transaction_ref``."""
    merchant = _merchant(session, tin)
    try:
        doc = registration.register_invoice_for_merchant(session, merchant, _tx_from(payload))
    except registration.RegistrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _resp(doc)


# --------------------------------------------------------------------------- #
# Cancel (spec §3) — irn in path; reason_code constrained to {1,2,3,4}
# --------------------------------------------------------------------------- #
@router.post("/invoices/{irn}/cancel", response_model=FiscalDocumentResponse)
def cancel_invoice(
    tin: str,
    irn: str,
    reason_code: CancelReasonCode = "3",
    remark: str = "",
    session: Session = Depends(get_session),
) -> FiscalDocumentResponse:
    """Cancel a registered invoice; persists MoR's returned cancelationDate."""
    merchant = _merchant(session, tin)
    try:
        doc = registration.cancel_invoice_for_document(
            session, merchant, irn, reason_code=reason_code, remark=remark
        )
    except registration.DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except registration.RegistrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return _resp(doc)


# --------------------------------------------------------------------------- #
# Verify (spec §3) — read-only at MoR
# --------------------------------------------------------------------------- #
@router.get("/invoices/{irn}/verify")
def verify_invoice(tin: str, irn: str, session: Session = Depends(get_session)) -> dict:
    """Verify an invoice by IRN at MoR (lowercase ``irn`` on the wire)."""
    merchant = _merchant(session, tin)
    return registration.verify_invoice_for_document(session, merchant, irn)


# --------------------------------------------------------------------------- #
# Sales receipt (spec §5)
# --------------------------------------------------------------------------- #
@router.post("/receipts", response_model=FiscalDocumentResponse)
def register_receipt(
    tin: str, payload: ReceiptRequest, session: Session = Depends(get_session)
) -> FiscalDocumentResponse:
    """Register a sales receipt for one or more registered invoices (reads body.rrn)."""
    merchant = _merchant(session, tin)
    rcpt = {
        "transaction_ref": payload.transaction_ref,
        "collected_amount": payload.collected_amount,
        "currency": payload.currency,
        "exchange_rate": payload.exchange_rate,
        "receipt_type": payload.receipt_type,
        "reason": payload.reason,
        "invoices": [i.model_dump() for i in payload.invoices],
        "transaction_details": payload.transaction_details.model_dump(),
    }
    try:
        doc = registration.register_receipt_for_document(session, merchant, rcpt)
    except registration.InvoiceCancelled as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except registration.DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except registration.RegistrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _resp(doc)


# --------------------------------------------------------------------------- #
# Credit / Debit notes (spec §4) — chained off the original invoice IRN
# --------------------------------------------------------------------------- #
@router.post("/credit-notes", response_model=FiscalDocumentResponse)
def credit_note(
    tin: str, payload: RegisterInvoiceRequest, session: Session = Depends(get_session)
) -> FiscalDocumentResponse:
    """Issue a credit note (CRE). Requires ``related_irn`` + ``reason``."""
    merchant = _merchant(session, tin)
    if not payload.related_irn:
        raise HTTPException(status_code=422, detail="related_irn is required for a credit note.")
    note = _tx_from(payload)
    note["related_irn"] = payload.related_irn
    note["reason"] = payload.reason
    try:
        doc = registration.issue_credit_note(session, merchant, note)
    except registration.InvoiceCancelled as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except registration.RegistrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _resp(doc)


@router.post("/debit-notes", response_model=FiscalDocumentResponse)
def debit_note(
    tin: str, payload: RegisterInvoiceRequest, session: Session = Depends(get_session)
) -> FiscalDocumentResponse:
    """Issue a debit note (DEB). Requires ``related_irn`` + ``reason``."""
    merchant = _merchant(session, tin)
    if not payload.related_irn:
        raise HTTPException(status_code=422, detail="related_irn is required for a debit note.")
    note = _tx_from(payload)
    note["related_irn"] = payload.related_irn
    note["reason"] = payload.reason
    try:
        doc = registration.issue_debit_note(session, merchant, note)
    except registration.InvoiceCancelled as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except registration.RegistrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _resp(doc)
