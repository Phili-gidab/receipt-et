"""Pure credit / debit note builders for MoR EIMS (spec §4).

Credit (CRE) and debit (DEB) notes are registered through the SAME
``/v1/register`` endpoint as invoices and are part of the same per-merchant
chain (own IRN + counter). They start from ``build_invoice`` and then mutate:

  * ``DocumentDetails.Type`` -> ``"CRE"`` / ``"DEB"``.
  * ``DocumentDetails.Reason`` -> a mandatory text (<=300 chars) — required for
    notes (rule 3.1.4.4).
  * ``ReferenceDetails.RelatedDocument`` -> the original invoice's **IRN string**
    (sandbox-proven 2026-06-12; referencing by document number resolves wrongly
    at MoR with errors 7020/7030).

Ported from the Delta reference (``eims.py`` ``_build_note`` lines 1162-1186) and
folded onto the multi-tenant / pure builder model. No I/O; reads fiscal values
only from the passed ``merchant``.

CRE guard: a credit note's ``ValueDetails.TotalValue`` must not exceed the
original invoice value (+0.005 tolerance). The caller supplies the original total
via ``original_total``; when omitted the guard is skipped (caller enforces it).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional, Sequence, Union

from app.invoice_builder import build_invoice

__all__ = ["build_credit_note", "build_debit_note"]


def _build_note(
    merchant,
    doc_type: str,
    *,
    document_number: Union[str, int],
    invoice_counter: int,
    previous_irn: Optional[str],
    related_irn: str,
    reason: str,
    buyer: Optional[Mapping[str, Any]] = None,
    items_or_single: Union[Mapping[str, Any], Sequence[Mapping[str, Any]]],
    amount: Optional[float] = None,
    currency: str = "ETB",
    payment_method: Optional[str] = None,
    exchange_rate: Optional[float] = None,
    original_total: Optional[float] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Build a CRE/DEB note (shared core). See module docstring for the rules."""
    if doc_type not in ("CRE", "DEB"):
        raise ValueError(f"EIMS: note doc_type must be CRE or DEB, got '{doc_type}'.")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError(
            f"EIMS: DocumentDetails.Reason is mandatory for {doc_type} notes."
        )
    related_irn = (str(related_irn).strip() if related_irn else "")
    if not related_irn:
        raise ValueError(
            "EIMS: RelatedDocument (original invoice IRN string) is mandatory "
            f"for {doc_type} notes."
        )

    note = build_invoice(
        merchant,
        document_number=document_number,
        invoice_counter=invoice_counter,
        previous_irn=previous_irn,
        buyer=buyer,
        items_or_single=items_or_single,
        amount=amount,
        currency=currency,
        payment_method=payment_method,
        exchange_rate=exchange_rate,
        now=now,
    )

    note["DocumentDetails"]["Type"] = doc_type
    note["DocumentDetails"]["Reason"] = reason[:300]
    # RelatedDocument is the original invoice's IRN STRING (NOT document number).
    note["ReferenceDetails"]["RelatedDocument"] = related_irn

    # CRE guard (spec §4 / do-not-inherit #4): credit must not exceed original.
    if doc_type == "CRE" and original_total is not None:
        credit_total = float(note.get("ValueDetails", {}).get("TotalValue") or 0)
        if credit_total > float(original_total) + 0.005:
            raise ValueError(
                f"EIMS: credit note total {credit_total} exceeds the original "
                f"invoice value {original_total}."
            )

    return note


def build_credit_note(
    merchant,
    *,
    document_number: Union[str, int],
    invoice_counter: int,
    previous_irn: Optional[str],
    related_irn: str,
    reason: str = "Refund / return of service",
    buyer: Optional[Mapping[str, Any]] = None,
    items_or_single: Union[Mapping[str, Any], Sequence[Mapping[str, Any]]],
    amount: Optional[float] = None,
    currency: str = "ETB",
    payment_method: Optional[str] = None,
    exchange_rate: Optional[float] = None,
    original_total: Optional[float] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Build a credit-note (CRE) ``/v1/register`` request for ``merchant``.

    ``related_irn`` is the original invoice's IRN string. ``original_total``, when
    given, enforces credit <= original (+0.005). Returns a dict with the spec §2
    top-level key order, with ``DocumentDetails.Type == "CRE"``, a non-empty
    ``Reason``, and ``ReferenceDetails.RelatedDocument == related_irn``.
    """
    return _build_note(
        merchant,
        "CRE",
        document_number=document_number,
        invoice_counter=invoice_counter,
        previous_irn=previous_irn,
        related_irn=related_irn,
        reason=reason,
        buyer=buyer,
        items_or_single=items_or_single,
        amount=amount,
        currency=currency,
        payment_method=payment_method,
        exchange_rate=exchange_rate,
        original_total=original_total,
        now=now,
    )


def build_debit_note(
    merchant,
    *,
    document_number: Union[str, int],
    invoice_counter: int,
    previous_irn: Optional[str],
    related_irn: str,
    reason: str = "Additional charge",
    buyer: Optional[Mapping[str, Any]] = None,
    items_or_single: Union[Mapping[str, Any], Sequence[Mapping[str, Any]]],
    amount: Optional[float] = None,
    currency: str = "ETB",
    payment_method: Optional[str] = None,
    exchange_rate: Optional[float] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Build a debit-note (DEB) ``/v1/register`` request for ``merchant``.

    ``related_irn`` is the original invoice's IRN string. Returns a dict with the
    spec §2 top-level key order, with ``DocumentDetails.Type == "DEB"``, a
    non-empty ``Reason``, and ``ReferenceDetails.RelatedDocument == related_irn``.
    """
    return _build_note(
        merchant,
        "DEB",
        document_number=document_number,
        invoice_counter=invoice_counter,
        previous_irn=previous_irn,
        related_irn=related_irn,
        reason=reason,
        buyer=buyer,
        items_or_single=items_or_single,
        amount=amount,
        currency=currency,
        payment_method=payment_method,
        exchange_rate=exchange_rate,
        now=now,
    )
