"""Print-ready HTML for fiscal documents — A4 and thermal (58/80mm).

Renders an invoice or receipt :class:`app.models.Document` (+ its merchant) into a
self-contained HTML string with the MoR-signed QR embedded as a data-URI PNG. The
line items and totals are read back from the canonical ``payload_json`` that was
sent to MoR, so the printout always matches what was registered.

Two formats via ``fmt``:
  * ``"a4"``      — full A4 page, two-column header, itemized table.
  * ``"thermal"`` — single 80mm (or 58mm) column for receipt printers.
"""

from __future__ import annotations

import json
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# Amount-in-words (Birr)
# --------------------------------------------------------------------------- #
_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_SCALE = [(1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand")]


def _three(n: int) -> str:
    out = []
    if n >= 100:
        out.append(_ONES[n // 100] + " hundred")
        n %= 100
    if n >= 20:
        out.append(_TENS[n // 10] + ((" " + _ONES[n % 10]) if n % 10 else ""))
    elif n > 0:
        out.append(_ONES[n])
    return " ".join(out)


def amount_to_words_birr(amount: float) -> str:
    """Render ``amount`` as English Birr + cents, e.g. 1150.50 -> 'one thousand
    one hundred fifty Birr and fifty cents'."""
    amount = round(float(amount or 0), 2)
    birr = int(amount)
    cents = int(round((amount - birr) * 100))
    if birr == 0:
        words = "zero"
    else:
        parts = []
        for value, name in _SCALE:
            if birr >= value:
                parts.append(_three(birr // value) + " " + name)
                birr %= value
        if birr:
            parts.append(_three(birr))
        words = " ".join(parts)
    out = f"{words} Birr"
    if cents:
        out += f" and {_three(cents)} cents"
    return out[:1].upper() + out[1:]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _payload(doc: Any) -> dict:
    if not getattr(doc, "payload_json", None):
        return {}
    try:
        return json.loads(doc.payload_json)
    except (TypeError, ValueError):
        return {}


def _qr_img(qr_b64: Optional[str], size_px: int = 150) -> str:
    if not qr_b64:
        return '<div class="noqr">[no QR]</div>'
    src = qr_b64 if qr_b64.startswith("data:") else f"data:image/png;base64,{qr_b64}"
    return f'<img class="qr" src="{src}" alt="MoR QR" style="width:{size_px}px;height:{size_px}px"/>'


def _esc(s: Any) -> str:
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_DOC_LABEL = {"INV": "TAX INVOICE", "CRE": "CREDIT NOTE", "DEB": "DEBIT NOTE", "RCP": "SALES RECEIPT"}


# --------------------------------------------------------------------------- #
# Invoice / note
# --------------------------------------------------------------------------- #
def render_invoice_html(doc: Any, merchant: Any, fmt: str = "a4") -> str:
    """Print-ready HTML for an INV/CRE/DEB document."""
    p = _payload(doc)
    seller = p.get("SellerDetails", {})
    buyer = p.get("BuyerDetails", {})
    items = p.get("ItemList", [])
    vals = p.get("ValueDetails", {})
    dd = p.get("DocumentDetails", {})
    currency = vals.get("InvoiceCurrency") or doc.currency or "ETB"
    label = _DOC_LABEL.get(doc.doc_type, "TAX INVOICE")
    thermal = fmt == "thermal"
    qr = _qr_img(doc.qr_b64, size_px=120 if thermal else 150)

    rows = "".join(
        f"<tr><td>{_esc(it.get('ProductDescription'))}</td>"
        f"<td class='r'>{_esc(it.get('Quantity'))}</td>"
        f"<td class='r'>{_esc(it.get('UnitPrice'))}</td>"
        f"<td class='r'>{_esc(it.get('TaxCode'))}</td>"
        f"<td class='r'>{_esc(it.get('TaxAmount'))}</td>"
        f"<td class='r'>{_esc(it.get('TotalLineAmount'))}</td></tr>"
        for it in items
    )
    vat_line = (
        "VAT EXEMPT" if str(vals.get("TaxValue", 0)) in ("0", "0.0", "0.00")
        else f"VAT: {_esc(vals.get('TaxValue'))} {currency}"
    )
    seller_vat = f"<div>VAT No: {_esc(seller.get('VatNumber'))}</div>" if seller.get("VatNumber") else ""
    buyer_block = ""
    if buyer:
        buyer_tin = f"<div>TIN: {_esc(buyer.get('Tin'))}</div>" if buyer.get("Tin") else ""
        buyer_block = (
            f"<div class='party'><b>Buyer</b><div>{_esc(buyer.get('LegalName'))}</div>{buyer_tin}</div>"
        )

    page_css = (
        "@page{size:80mm auto;margin:3mm} body{width:74mm;font:11px monospace}"
        if thermal
        else "@page{size:A4;margin:16mm} body{font:13px/1.45 Arial,sans-serif}"
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{label} {_esc(doc.document_number)}</title>
<style>
{page_css}
.head{{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #111;padding-bottom:8px}}
.brand{{font-weight:700;font-size:1.3em}}
.doclabel{{font-weight:700;letter-spacing:1px}}
table{{width:100%;border-collapse:collapse;margin:10px 0}}
th,td{{border-bottom:1px solid #ddd;padding:5px;text-align:left}}
td.r,th.r{{text-align:right}}
.totals{{margin-top:8px}} .totals div{{display:flex;justify-content:space-between}}
.grand{{font-weight:700;border-top:2px solid #111;padding-top:4px}}
.party{{margin:8px 0}} .irn{{word-break:break-all;font-size:.85em;color:#333}}
.qrwrap{{text-align:center;margin-top:10px}} .noqr{{color:#999}}
.words{{font-style:italic;margin-top:6px}} .foot{{margin-top:10px;font-size:.8em;color:#555;text-align:center}}
</style></head><body>
<div class="head">
  <div><div class="brand">{_esc(merchant.legal_name)}</div>
    <div>TIN: {_esc(merchant.tin)}</div>{seller_vat}
    <div>{_esc(merchant.city or '')} {_esc(merchant.kebele or '')}</div>
  </div>
  <div style="text-align:right">
    <div class="doclabel">{label}</div>
    <div>No: {_esc(doc.document_number)}</div>
    <div>Date: {_esc(dd.get('Date'))}</div>
  </div>
</div>
{buyer_block}
<table><thead><tr><th>Description</th><th class="r">Qty</th><th class="r">Unit</th>
<th class="r">Tax</th><th class="r">Tax Amt</th><th class="r">Line Total</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="totals">
  <div><span>Subtotal (pre-tax)</span><span>{_esc(round(float(vals.get('TotalValue', 0)) - float(vals.get('TaxValue', 0)), 2))} {currency}</span></div>
  <div><span>{vat_line}</span><span></span></div>
  <div class="grand"><span>TOTAL</span><span>{_esc(vals.get('TotalValue'))} {currency}</span></div>
</div>
<div class="words">In words: {amount_to_words_birr(vals.get('TotalValue') or doc.amount or 0)}</div>
<div class="irn">IRN: {_esc(doc.irn)}</div>
<div class="qrwrap">{qr}</div>
<div class="foot">Government-verified via Ministry of Revenue EIMS · scan the QR to verify</div>
</body></html>"""


# --------------------------------------------------------------------------- #
# Sales receipt
# --------------------------------------------------------------------------- #
def render_receipt_html(doc: Any, merchant: Any, fmt: str = "a4") -> str:
    """Print-ready HTML for a sales-receipt (RCP) document — shows RRN + QR."""
    p = _payload(doc)
    currency = p.get("ReceiptCurrency") or doc.currency or "ETB"
    thermal = fmt == "thermal"
    qr = _qr_img(doc.qr_b64, size_px=120 if thermal else 150)
    inv_rows = "".join(
        f"<tr><td class='irn'>{_esc(inv.get('InvoiceIRN'))}</td>"
        f"<td class='r'>{_esc(inv.get('PaymentCoverage'))}</td>"
        f"<td class='r'>{_esc(inv.get('InvoicePaidAmount'))}</td></tr>"
        for inv in p.get("Invoices", [])
    )
    page_css = (
        "@page{size:80mm auto;margin:3mm} body{width:74mm;font:11px monospace}"
        if thermal
        else "@page{size:A4;margin:16mm} body{font:13px/1.45 Arial,sans-serif}"
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>RECEIPT {_esc(doc.rrn)}</title>
<style>
{page_css}
.head{{text-align:center;border-bottom:2px solid #111;padding-bottom:8px}}
.brand{{font-weight:700;font-size:1.3em}}
table{{width:100%;border-collapse:collapse;margin:10px 0}}
th,td{{border-bottom:1px solid #ddd;padding:5px;text-align:left}} td.r,th.r{{text-align:right}}
.grand{{font-weight:700;display:flex;justify-content:space-between;border-top:2px solid #111;padding-top:4px}}
.irn{{word-break:break-all;font-size:.8em}} .rrn{{font-weight:700;margin-top:6px}}
.qrwrap{{text-align:center;margin-top:10px}} .noqr{{color:#999}}
.foot{{margin-top:10px;font-size:.8em;color:#555;text-align:center}}
</style></head><body>
<div class="head"><div class="brand">{_esc(merchant.legal_name)}</div>
  <div>TIN: {_esc(merchant.tin)}</div><div>SALES RECEIPT</div>
  <div>Date: {_esc(p.get('ReceiptDate'))}</div></div>
<table><thead><tr><th>Invoice IRN</th><th class="r">Coverage</th><th class="r">Paid</th></tr></thead>
<tbody>{inv_rows}</tbody></table>
<div class="grand"><span>COLLECTED</span><span>{_esc(p.get('CollectedAmount') or doc.amount)} {currency}</span></div>
<div class="rrn">RRN: {_esc(doc.rrn)}</div>
<div class="qrwrap">{qr}</div>
<div class="foot">Government-verified via Ministry of Revenue EIMS · scan the QR to verify</div>
</body></html>"""
