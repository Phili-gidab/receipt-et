"""Pure sales-receipt builder for MoR EIMS ``/v1/receipt/sales`` (spec §5).

⚠️ SANDBOX-UNVALIDATED. This is the path the project owner specifically wants
working in sandbox; treat the field shape as best-guess until the first clean
round-trip and iterate against MoR's response on a 400/406.

Differences from invoices (spec §5):
  * Date format is ISO-8601 with the EAT (+03:00) offset, NOT the invoice
    ``dd-MM-yyyy'T'HH:mm:ss`` form: ``RECEIPT_DATE_FORMAT``.
  * Not chained (no PreviousIrn).
  * Success is read from ``body.rrn`` (Receipt Reference Number), not ``body.irn``
    (do-not-inherit #3).

Ported from the Delta reference (``eims.py`` ``build_sales_receipt`` lines
1189-1221) and folded onto the multi-tenant / pure builder model. No I/O; reads
fiscal values only from the passed ``merchant``. Cancelled-invoice guarding (a
receipt must not be issued against a cancelled invoice) is enforced upstream by
the caller that knows each invoice's fiscal status (spec §5 / do-not-inherit #5).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

__all__ = ["RECEIPT_DATE_FORMAT", "build_sales_receipt"]

# Receipt date format DIFFERS from invoices: ISO-8601 with the EAT offset, e.g.
# "2026-06-29T14:30:00.000+03:00" (spec §5). The +03:00 is hard-coded because
# the seller operates in Africa/Addis_Ababa (no DST).
RECEIPT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.000+03:00"


def build_sales_receipt(
    merchant,
    *,
    invoices: Sequence[Mapping[str, Any]],
    collected_amount: float,
    receipt_counter: int,
    reason: Optional[str] = None,
    txn_details: Optional[Mapping[str, Any]] = None,
    receipt_number: Optional[str] = None,
    receipt_type: str = "Sales Receipts",
    currency: str = "ETB",
    exchange_rate: Optional[float] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Build a ``/v1/receipt/sales`` request object for ``merchant`` (spec §5).

    Pure: reads fiscal values only from ``merchant``; performs no I/O.

    Args:
        merchant: merchant row (``app.models.Merchant`` or compatible). SellerTIN
            and the source system type/number are read from it.
        invoices: sequence of ``{"irn": <str>, "amount": <float>}`` mappings — the
            invoices this receipt covers. Each becomes an ``Invoices[]`` entry
            with ``PaymentCoverage="FULL"`` and ``InvoicePaidAmount`` /
            ``TotalAmount`` = its amount. (Optional per-invoice overrides:
            ``payment_coverage``, ``invoice_paid_amount``, ``total_amount``.)
        collected_amount: total amount collected on this receipt.
        receipt_counter: current counter (stringified on the wire per spec §5).
        reason: receipt reason text (optional).
        txn_details: payment metadata mapping with optional keys
            ``mode_of_payment`` (enum, default CASH), ``collector_name``,
            ``payment_service_provider``, ``account_number``,
            ``transaction_number``.
        receipt_number: explicit ReceiptNumber (<=20 chars). Defaults to
            ``"REC-<receipt_counter>"`` when not given.
        receipt_type: ReceiptType (default "Sales Receipts").
        currency: ReceiptCurrency (default "ETB").
        exchange_rate: ExchangeRate; serialized as JSON ``null`` for ETB, else
            REQUIRED (raises if currency != ETB and not supplied).
        now: timestamp for ReceiptDate; defaults to ``datetime.now()``.

    Returns:
        A dict with keys in the exact spec §5 order. The caller signs it with
        ``app.crypto.build_signed_body`` and POSTs to ``/v1/receipt/sales``;
        success is read from ``body.rrn``.

    Raises:
        ValueError: missing seller TIN, no invoices, or a non-ETB currency with
            no ``exchange_rate``.
    """
    if not getattr(merchant, "tin", None):
        raise ValueError("EIMS: merchant.tin is required for SellerTIN.")

    invoice_list = list(invoices or [])
    if not invoice_list:
        raise ValueError("EIMS: a sales receipt needs at least one invoice.")

    when = now or datetime.now()
    currency = (currency or "ETB").upper()

    if currency != "ETB":
        if exchange_rate is None:
            raise ValueError(
                f"EIMS: currency '{currency}' != ETB requires an exchange_rate."
            )
        exchange_value: Optional[float] = float(exchange_rate)
    else:
        # ETB -> JSON null (matches spec §5 example).
        exchange_value = None

    invoices_block = []
    for inv in invoice_list:
        irn = inv.get("irn")
        if not irn:
            raise ValueError("EIMS: each receipt invoice needs an 'irn'.")
        amount = float(inv.get("amount", 0) or 0)
        invoices_block.append({
            "InvoiceIRN": str(irn),
            "PaymentCoverage": str(inv.get("payment_coverage") or "FULL"),
            "InvoicePaidAmount": float(inv.get("invoice_paid_amount", amount)),
            "TotalAmount": float(inv.get("total_amount", amount)),
        })

    td = dict(txn_details or {})
    mode = str(td.get("mode_of_payment") or "CASH").strip().upper()
    if mode not in {"CASH", "ADVANCE", "CREDIT"}:
        mode = "CASH"

    number = receipt_number or f"REC-{receipt_counter}"

    # Key order is contract-critical (spec §5).
    receipt = {
        "ReceiptNumber": str(number)[:20],
        "ReceiptType": str(receipt_type or "Sales Receipts"),
        "Reason": str(reason or ""),
        "ReceiptDate": when.strftime(RECEIPT_DATE_FORMAT),
        "ReceiptCounter": str(receipt_counter),
        "SourceSystemType": str(getattr(merchant, "system_type", None) or ""),
        "SourceSystemNumber": str(getattr(merchant, "system_number", None) or ""),
        "ReceiptCurrency": currency,
        "ExchangeRate": exchange_value,
        "CollectedAmount": float(collected_amount),
        "SellerTIN": str(merchant.tin),
        "Invoices": invoices_block,
        "TransactionDetails": {
            "ModeOfPayment": mode,
            "CollectorName": str(
                td.get("collector_name")
                or getattr(merchant, "legal_name", None)
                or ""
            ),
            "PaymentServiceProvider": str(td.get("payment_service_provider") or "Online"),
            "AccountNumber": str(td.get("account_number") or "N/A"),
            "TransactionNumber": str(td.get("transaction_number") or "N/A"),
        },
    }
    return receipt
