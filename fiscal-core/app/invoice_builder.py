"""Pure invoice payload builder for the MoR EIMS ``/v1/register`` call.

Ported from the sandbox-validated Delta implementation
(``Delta_SPMU/backend/frappe-lms/lms/lms/eims.py`` ``build_invoice`` lines
429-588) and folded onto the multi-tenant contract in MOR_EIMS_CONTRACT.md §2.

DESIGN — multi-tenant / pure
----------------------------
Delta was single-tenant: every fiscal value (TIN, system type/number, tax code,
VAT number, seller address, VAT-inclusive flag) came from one global config. In
Receipt each of those is **per-merchant state**. So ``build_invoice`` takes a
``Merchant`` (the ``app.models.Merchant`` ORM row, or any object with the same
attributes) and reads fiscal values **only** from it — never from a global. The
function performs no I/O and returns a plain ``dict`` whose **top-level keys are
in the exact contract order** (canonical signing depends on it, spec §2):

    TransactionType, DocumentDetails, SourceSystem, SellerDetails, BuyerDetails,
    ItemList, PaymentDetails, ValueDetails, ReferenceDetails, Version

Crypto/transport (signing, envelope) lives in ``app.crypto``; this module only
shapes the ``request`` object.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence, Union

__all__ = [
    "DOC_DATE_FORMAT",
    "PAYMENT_TERM",
    "UNIT_OF_MEASURE",
    "NATURE_OF_SUPPLIES",
    "VALID_ID_TYPES",
    "build_invoice",
]

# ASSUMPTION carried over from Delta + spec §2: live MoR examples use
# "29-06-2026T14:30:00" (dd-MM-yyyy'T'HH:mm:ss), NOT ISO-8601.
DOC_DATE_FORMAT = "%d-%m-%YT%H:%M:%S"

# Const line-item / payment values (spec §2). PAYMENT_TERM keeps MoR's [sic]
# misspelling on the wire.
PAYMENT_TERM = "IMMIDIATE"
UNIT_OF_MEASURE = "PCS"
NATURE_OF_SUPPLIES = "service"  # MoR enum is lowercase: 'goods' | 'service'

# B2C registered-ID enum (spec §2, error 7004).
VALID_ID_TYPES = {"NID", "KID", "SID", "WID", "PST", "DLS", "MRS"}

# PaymentDetails.Mode enum (spec §2 / do-not-inherit #6). Default CASH, NEVER
# the invalid "Direct Transfer".
VALID_PAYMENT_MODES = {"CASH", "ADVANCE", "CREDIT"}

# SellerDetails optional fields -> Merchant attribute names. Sent ONLY when the
# merchant has the value set AND it is confirmed to match MoR's record exactly
# (exact-match rule, error 7017); omitted ones are auto-filled by MoR.
_SELLER_OPTIONAL = (
    ("VatNumber", "vat_number"),
    ("Region", "region"),
    ("City", "city"),
    ("Wereda", "wereda"),
    ("Kebele", "kebele"),
    ("SubCity", "subcity"),
    ("HouseNumber", "house_number"),
    ("Country", "country"),
    ("Locality", "locality"),
    ("Email", "email"),
    ("Phone", "phone"),
)

# MoR phone rule: optional "+" then >=6 digits.
_PHONE_RE = re.compile(r"^\+?[0-9]{6,}$")


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def _vat_rate(tax_code: Optional[str]) -> float:
    """VAT percentage parsed from the code: VAT15 -> 15, VAT0 -> 0, VATEX -> 0,
    non-VAT -> 0."""
    code = (tax_code or "").upper()
    if code.startswith("VAT"):
        digits = code[3:]
        try:
            return float(digits) if digits else 0.0
        except ValueError:
            return 0.0
    return 0.0


def _split_amount(
    amount: float, tax_code: Optional[str], *, vat_inclusive: bool = True
) -> tuple[float, float, float]:
    """Return ``(pre_tax, tax_amount, line_total)`` for a charged amount.

    When ``vat_inclusive`` (the default, per-merchant ``price_vat_inclusive``),
    the charged amount already contains VAT and is split:
    ``pre_tax = round(amount / (1 + rate/100), 2)`` — e.g. 100 ETB @ VAT15 ->
    (86.96, 13.04, 100.0). Otherwise tax is added on top. VATEX / non-VAT codes
    have rate 0 -> ``(amount, 0.0, amount)``.
    """
    rate = _vat_rate(tax_code)
    if rate and vat_inclusive:
        pre_tax = round(amount / (1 + rate / 100.0), 2)
        return pre_tax, round(amount - pre_tax, 2), round(amount, 2)
    if rate:
        pre_tax = round(amount, 2)
        tax = round(amount * rate / 100.0, 2)
        return pre_tax, tax, round(pre_tax + tax, 2)
    pre_tax = round(amount, 2)
    return pre_tax, 0.0, pre_tax


def _clean_phone(raw: Any) -> Optional[str]:
    """Normalise a phone to MoR's ``^\\+?[0-9]{6,}$``, or ``None`` if it can't
    satisfy it (so the optional field is OMITTED, never sent blank — spec §2)."""
    if not raw:
        return None
    s = str(raw).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) < 6:
        return None
    candidate = ("+" + digits) if s.startswith("+") else digits
    return candidate if _PHONE_RE.match(candidate) else None


def _seller_details(merchant) -> dict:
    """Build SellerDetails for ``merchant``.

    ``Tin`` + ``LegalName`` are sent unconditionally; every other field is sent
    ONLY when set on the merchant (exact-match rule, error 7017). Reads fiscal
    values from the merchant ONLY — never a global.
    """
    if not getattr(merchant, "tin", None):
        raise ValueError("EIMS: merchant.tin is required for SellerDetails.")
    if not getattr(merchant, "legal_name", None):
        raise ValueError("EIMS: merchant.legal_name is required for SellerDetails.")

    seller = {
        "Tin": str(merchant.tin),
        "LegalName": str(merchant.legal_name),
    }
    for field, attr in _SELLER_OPTIONAL:
        val = getattr(merchant, attr, None)
        if val not in (None, ""):
            seller[field] = str(val)
    return seller


def _normalize_items(
    items_or_single: Union[Mapping[str, Any], Sequence[Mapping[str, Any]]],
) -> list[Mapping[str, Any]]:
    """Accept either a single item mapping or a sequence of them -> list."""
    if isinstance(items_or_single, Mapping):
        return [items_or_single]
    items = list(items_or_single)
    if not items:
        raise ValueError("EIMS: at least one item is required.")
    return items


def _line_tax_code(item: Mapping[str, Any], merchant) -> str:
    """Per-line tax code: an explicit item override wins, else the merchant's."""
    code = item.get("tax_code") or getattr(merchant, "tax_code", None)
    if not code:
        raise ValueError("EIMS: no TaxCode set on item or merchant.")
    return str(code)


# --------------------------------------------------------------------------- #
# Builder
# --------------------------------------------------------------------------- #
def build_invoice(
    merchant,
    *,
    document_number: Union[str, int],
    invoice_counter: int,
    previous_irn: Optional[str],
    buyer: Optional[Mapping[str, Any]] = None,
    items_or_single: Union[Mapping[str, Any], Sequence[Mapping[str, Any]]],
    amount: Optional[float] = None,
    currency: str = "ETB",
    payment_method: Optional[str] = None,
    exchange_rate: Optional[float] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Build the EIMS ``/v1/register`` request object for ``merchant``.

    Pure: reads fiscal values only from ``merchant``; performs no I/O.

    Args:
        merchant: the merchant row (``app.models.Merchant`` or compatible). VAT
            number, tax code, system type/number, seller details and the
            ``price_vat_inclusive`` flag are read from it.
        document_number: the seller's sequential invoice number (stringified).
        invoice_counter: running counter (int) for SourceSystem.InvoiceCounter.
        previous_irn: IRN of the previously registered document, or a falsy value
            for the **first** invoice -> serialized as JSON ``null`` (spec §7.1).
        buyer: optional mapping with ``legal_name``/``email``/``phone``/
            ``id_type``/``id_number``/``tin``. Presence of ``tin`` -> B2B.
        items_or_single: one item mapping or a sequence of them. Each item:
            ``item_code``, ``product_description``, ``unit_price`` (per the
            ``price_vat_inclusive`` flag), optional ``quantity`` (default 1),
            ``discount`` (default 0), ``nature_of_supplies`` (default
            ``"service"``), ``unit`` (default ``"PCS"``), ``tax_code`` override.
            When ``amount`` is given AND exactly one item is supplied, ``amount``
            is treated as the VAT-inclusive line total (parity with Delta's
            single-line ``build_invoice``).
        amount: optional single-line charged amount (VAT-inclusive). Used only
            for a single-item invoice; ignored when multiple items are passed.
        currency: invoice currency (default ``"ETB"``).
        payment_method: caller payment channel; mapped to a Mode enum. Unknown /
            absent -> **CASH** (never the invalid "Direct Transfer", spec §6).
        exchange_rate: float, REQUIRED when ``currency != "ETB"`` (added to
            ValueDetails as ``ExchangeRate``).
        now: timestamp for DocumentDetails.Date; defaults to ``datetime.now()``.

    Returns:
        A dict with top-level keys in the exact spec §2 order.

    Raises:
        ValueError: missing seller TIN/LegalName, VAT* TaxCode without a merchant
            VatNumber (rule 3.1.4.4), bad buyer IdType, B2B without a valid buyer
            TIN, or a non-ETB currency with no exchange_rate.
    """
    when = now or datetime.now()
    currency = (currency or "ETB").upper()
    vat_inclusive = bool(getattr(merchant, "price_vat_inclusive", True))

    items = _normalize_items(items_or_single)
    single = len(items) == 1

    # ---- Build line items + tally totals ----
    item_list: list[dict] = []
    total_value = 0.0
    tax_value = 0.0
    for idx, raw in enumerate(items, start=1):
        tax_code = _line_tax_code(raw, merchant)

        # VAT rule (spec §2, rule 3.1.4.4): any VAT-prefixed TaxCode requires
        # SellerDetails.VatNumber. Fail fast rather than eat a cryptic 406.
        if tax_code.upper().startswith("VAT") and not getattr(merchant, "vat_number", None):
            raise ValueError(
                f"EIMS: TaxCode '{tax_code}' is VAT-prefixed, which requires "
                f"SellerDetails.VatNumber, but merchant.vat_number is not set."
            )

        quantity = float(raw.get("quantity", 1) or 1)
        discount = float(raw.get("discount", 0) or 0)

        if single and amount is not None:
            line_amount = float(amount)
        else:
            line_amount = float(raw["unit_price"]) * quantity - discount

        # MoR line validation (sandbox-observed across three rejections): the
        # gateway recomputes UnitPrice*Quantity*(1+rate), quantizes HALF_UP to
        # the same number of decimals as the UnitPrice we sent, and requires
        # TotalLineAmount to match EXACTLY ("expected 80.01 received 80.0" for
        # a 2dp unit; "expected 2999.9999 received 3000.0" for a 4dp unit). So:
        # send 2dp units and search the neighbouring cents for the unit whose
        # reconstruction lands exactly on the charged amount; when no cent can
        # (e.g. 80.00 @ VAT15 is unreachable), take the closest reconstructable
        # total — the fiscal document then differs from the sticker by <=0.01,
        # which is unavoidable under MoR's own arithmetic.
        from decimal import ROUND_HALF_UP, Decimal

        rate = _vat_rate(tax_code)
        q2 = Decimal("0.01")
        d_qty = Decimal(str(quantity or 1))
        factor = (Decimal(1) + Decimal(str(rate)) / Decimal(100)) if rate else Decimal(1)
        d_line = Decimal(str(round(line_amount, 2)))
        base = (d_line / d_qty / factor) if vat_inclusive or not rate else (d_line / d_qty)
        base = base.quantize(q2, rounding=ROUND_HALF_UP)

        def _is_tie(x: Decimal) -> bool:
            # exact .xx5 remainder: HALF_UP vs HALF_EVEN disagree and MoR's
            # tie-break is unknown — treat such candidates as ambiguous
            return (x * 100) % 1 == Decimal("0.5")

        target = d_line if (vat_inclusive or not rate) else (d_line * factor).quantize(q2, rounding=ROUND_HALF_UP)
        rate_q = Decimal(str(rate)) / Decimal(100)
        best = None  # (err, tie, cand, recon)
        for cents in (0, 1, -1, 2, -2):
            cand = base + Decimal(cents) / Decimal(100)
            if cand <= 0:
                continue
            gross_prod = cand * d_qty * factor
            tax_prod = cand * d_qty * rate_q
            tie = _is_tie(gross_prod) or _is_tie(tax_prod)
            recon = gross_prod.quantize(q2, rounding=ROUND_HALF_UP)
            # ambiguity trumps drift: a tie may be rejected outright depending
            # on MoR's tie-break, while a couple cents of drift always registers
            key = (tie, abs(recon - target))
            if best is None or key < best[:2]:
                best = (key[0], key[1], cand, recon)
            if key == (False, 0):
                break
        _, _, best_unit, best_total = best

        # Each field is validated independently against its own product from
        # the sent unit ("taxAmount expected 26.0870 received 26.09"), so
        # quantize each product directly — never derive one by subtraction.
        rate_frac = Decimal(str(rate)) / Decimal(100)
        unit_price = float(best_unit)
        line_total = float(best_total)
        pre_tax = float((best_unit * d_qty).quantize(q2, rounding=ROUND_HALF_UP))
        tax_amount = float((best_unit * d_qty * rate_frac).quantize(q2, rounding=ROUND_HALF_UP))

        item_list.append({
            "LineNumber": idx,
            "NatureOfSupplies": str(raw.get("nature_of_supplies") or NATURE_OF_SUPPLIES),
            "ItemCode": str(raw.get("item_code") or "")[:15],
            "ProductDescription": str(raw.get("product_description") or "")[:300],
            "Unit": str(raw.get("unit") or UNIT_OF_MEASURE),
            "UnitPrice": unit_price,
            "Quantity": quantity,
            "Discount": discount,
            "PreTaxValue": pre_tax,
            "ExciseTaxValue": 0,
            "TaxCode": tax_code,
            "TaxAmount": tax_amount,
            "TotalLineAmount": line_total,
        })
        total_value += line_total
        tax_value += tax_amount

    total_value = round(total_value, 2)
    tax_value = round(tax_value, 2)

    # ---- Buyer (default B2C) ----
    buyer = dict(buyer or {})
    buyer_block: dict = {"LegalName": str(buyer.get("legal_name") or "Customer")}

    email = (buyer.get("email") or "").strip() if buyer.get("email") else ""
    if email:
        buyer_block["Email"] = email

    phone = _clean_phone(buyer.get("phone"))
    if phone:
        buyer_block["Phone"] = phone

    # B2C registered-ID (error 7004). Per-buyer values win; else merchant
    # defaults (used for sandbox testing with MoR's seeded IDs).
    id_type = (buyer.get("id_type") or getattr(merchant, "default_buyer_id_type", None) or "")
    id_number = (buyer.get("id_number") or getattr(merchant, "default_buyer_id_number", None) or "")
    id_type = str(id_type).strip()
    id_number = str(id_number).strip()
    if id_type and id_number:
        if id_type not in VALID_ID_TYPES:
            raise ValueError(
                f"EIMS: invalid buyer IdType '{id_type}'; "
                f"must be one of {sorted(VALID_ID_TYPES)} (error 7004)."
            )
        buyer_block["IdType"] = id_type
        buyer_block["IdNumber"] = id_number

    buyer_tin = (str(buyer.get("tin")).strip() if buyer.get("tin") else "")
    if buyer_tin:
        # B2B guard (do-not-inherit #8): 10-digit TIN + non-empty LegalName.
        if not re.fullmatch(r"[0-9]{10}", buyer_tin):
            raise ValueError(
                f"EIMS: B2B buyer TIN must be 10 digits, got '{buyer_tin}'."
            )
        if not (buyer.get("legal_name") or "").strip():
            raise ValueError("EIMS: B2B requires a non-empty buyer LegalName.")
        transaction_type = "B2B"
        buyer_block["Tin"] = buyer_tin
    else:
        transaction_type = "B2C"

    # ---- Payment mode (default CASH, never "Direct Transfer") ----
    mode = (payment_method or "").strip().upper()
    if mode not in VALID_PAYMENT_MODES:
        mode = "CASH"

    # ---- ValueDetails ----
    value_details = {
        "TotalValue": total_value,
        "TaxValue": tax_value,
        "ExciseValue": 0,
        "TransactionWithholdValue": 0,
        "IncomeWithholdValue": 0,
        "InvoiceCurrency": currency,
    }
    if currency != "ETB":
        if exchange_rate is None:
            raise ValueError(
                f"EIMS: currency '{currency}' != ETB requires an exchange_rate."
            )
        value_details["ExchangeRate"] = float(exchange_rate)

    # ---- Assemble (top-level key order is contract-critical, spec §2) ----
    invoice = {
        "TransactionType": transaction_type,
        "DocumentDetails": {
            "Type": "INV",
            "DocumentNumber": str(document_number),
            "Date": when.strftime(DOC_DATE_FORMAT),
        },
        "SourceSystem": {
            "SystemType": str(getattr(merchant, "system_type", None) or ""),
            "SystemNumber": str(getattr(merchant, "system_number", None) or ""),
            "InvoiceCounter": int(invoice_counter),
        },
        "SellerDetails": _seller_details(merchant),
        "BuyerDetails": buyer_block,
        "ItemList": item_list,
        "PaymentDetails": {
            "PaymentTerm": PAYMENT_TERM,
            "Mode": mode,
        },
        "ValueDetails": value_details,
        "ReferenceDetails": {
            # First invoice -> JSON null, never "" (spec §7.1).
            "PreviousIrn": previous_irn or None,
            "RelatedDocument": None,
        },
        "Version": "1",
    }
    return invoice
