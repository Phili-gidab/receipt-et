"""Day-close (Z-report) aggregation — shared by the web app and Telegram bot.

A "day" is the Africa/Addis_Ababa calendar day (UTC+3, no DST); documents are
stored with UTC timestamps, so the day window is converted before querying.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, FiscalStatus, Merchant

ADDIS_TZ = timezone(timedelta(hours=3))


@dataclass
class ZReport:
    day: date
    docs: list[Document]
    inv_count: int
    gross: float
    refunds: float
    net: float
    vat_out: float
    rcp_count: int
    voided_count: int
    failed_count: int


def _vat_of(d: Document) -> float:
    try:
        return float((json.loads(d.payload_json or "{}").get("ValueDetails") or {}).get("TaxValue") or 0)
    except Exception:
        return 0.0


def _window_docs(db: Session, merchant: Merchant, start_utc: datetime, end_utc: datetime) -> list[Document]:
    return list(db.execute(
        select(Document).where(
            Document.merchant_id == merchant.id,
            Document.created_at >= start_utc,
            Document.created_at < end_utc,
        ).order_by(Document.created_at.asc())
    ).scalars())


def _local_midnight_utc(day: date) -> datetime:
    """Addis local midnight of ``day`` converted to the UTC instant stored in the DB."""
    return datetime(day.year, day.month, day.day, tzinfo=ADDIS_TZ).astimezone(timezone.utc)


def _aggregate(docs: list[Document]) -> dict:
    inv = [d for d in docs if d.doc_type == "INV" and d.fiscal_status == FiscalStatus.REGISTERED]
    cre = [d for d in docs if d.doc_type == "CRE" and d.fiscal_status == FiscalStatus.REGISTERED]
    gross = sum(float(d.amount or 0) for d in inv)
    refunds = sum(float(d.amount or 0) for d in cre)
    return {
        "inv_count": len(inv),
        "gross": gross,
        "refunds": refunds,
        "net": gross - refunds,
        "vat_out": sum(_vat_of(d) for d in inv) - sum(_vat_of(d) for d in cre),
        "rcp_count": sum(1 for d in docs if d.doc_type == "RCP" and d.fiscal_status == FiscalStatus.REGISTERED),
        "voided_count": sum(1 for d in docs if d.fiscal_status == FiscalStatus.CANCELLED),
        "failed_count": sum(1 for d in docs if d.fiscal_status == FiscalStatus.FAILED),
    }


def zreport_for_day(db: Session, merchant: Merchant, day: date | None = None) -> ZReport:
    if day is None:
        day = datetime.now(ADDIS_TZ).date()
    start_utc = _local_midnight_utc(day)
    docs = _window_docs(db, merchant, start_utc, start_utc + timedelta(days=1))
    return ZReport(day=day, docs=docs, **_aggregate(docs))


@dataclass
class RangeReport:
    """Aggregates for an inclusive Addis-day range [start_day, end_day]."""

    start_day: date
    end_day: date
    docs: list[Document]
    inv_count: int
    gross: float
    refunds: float
    net: float
    vat_out: float
    rcp_count: int
    voided_count: int
    failed_count: int
    days: list[dict]        # [{day, net, vat_out, inv_count, refunds}]
    top_items: list[dict]   # [{name, qty, amount}] from registered INV ItemLists


def range_report(db: Session, merchant: Merchant, start_day: date, end_day: date) -> RangeReport:
    """Date-range report (both ends inclusive, Addis calendar days).

    Same window math and aggregation as the Z-report — one code path for every
    channel and report type. ``vat_out`` is the merchant's output-VAT position
    for the range: TaxValue of registered invoices minus credit notes, i.e.
    the number their monthly VAT declaration starts from.
    """
    if end_day < start_day:
        start_day, end_day = end_day, start_day
    start_utc = _local_midnight_utc(start_day)
    end_utc = _local_midnight_utc(end_day + timedelta(days=1))
    docs = _window_docs(db, merchant, start_utc, end_utc)

    # Per-day rows (Addis calendar) — days without documents still appear.
    by_day: dict[date, list[Document]] = {}
    for d in docs:
        local_day = d.created_at.astimezone(ADDIS_TZ).date() if d.created_at else start_day
        by_day.setdefault(local_day, []).append(d)
    days = []
    cursor = start_day
    while cursor <= end_day:
        agg = _aggregate(by_day.get(cursor, []))
        days.append({"day": cursor, "net": agg["net"], "vat_out": agg["vat_out"],
                     "inv_count": agg["inv_count"], "refunds": agg["refunds"]})
        cursor += timedelta(days=1)

    # Top items across registered invoices (by amount sold).
    tally: dict[str, dict] = {}
    for d in docs:
        if d.doc_type != "INV" or d.fiscal_status != FiscalStatus.REGISTERED:
            continue
        try:
            item_list = (json.loads(d.payload_json or "{}").get("ItemList")) or []
        except Exception:
            continue
        for it in item_list:
            key = (it.get("ProductDescription") or it.get("ItemCode") or "Item")[:80]
            row = tally.setdefault(key, {"name": key, "qty": 0.0, "amount": 0.0})
            row["qty"] += float(it.get("Quantity") or 0)
            row["amount"] += float(it.get("TotalLineAmount") or 0)
    top_items = sorted(tally.values(), key=lambda r: -r["amount"])[:8]

    return RangeReport(start_day=start_day, end_day=end_day, docs=docs,
                       days=days, top_items=top_items, **_aggregate(docs))
