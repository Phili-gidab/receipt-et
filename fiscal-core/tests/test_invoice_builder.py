"""Tests for app.invoice_builder — VAT split + spec §2 contract shape.

These import ONLY app.invoice_builder (pure, stdlib-only) and use a lightweight
``FakeMerchant`` so they run without a database, FastAPI, or service config
(same approach as tests/test_crypto.py).

Anchor assertions (from the spec / prompt):
  * 100 ETB @ VAT15 (VAT-inclusive) -> PreTax 86.96 / Tax 13.04 / Total 100.0.
  * top-level keys appear in the exact spec §2 order.
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.invoice_builder import (
    _clean_phone,
    _split_amount,
    build_invoice,
)

# Spec §2 canonical top-level key order.
EXPECTED_TOP_LEVEL_ORDER = [
    "TransactionType",
    "DocumentDetails",
    "SourceSystem",
    "SellerDetails",
    "BuyerDetails",
    "ItemList",
    "PaymentDetails",
    "ValueDetails",
    "ReferenceDetails",
    "Version",
]

# Spec §2 per-line key order (13 keys).
EXPECTED_ITEM_ORDER = [
    "LineNumber", "NatureOfSupplies", "ItemCode", "ProductDescription", "Unit",
    "UnitPrice", "Quantity", "Discount", "PreTaxValue", "ExciseTaxValue",
    "TaxCode", "TaxAmount", "TotalLineAmount",
]

FIXED_NOW = datetime(2026, 6, 29, 14, 30, 0)


def make_merchant(**overrides):
    """A VAT-registered merchant (Delta seed values), overridable per test."""
    base = dict(
        tin="0107184904",
        legal_name="DELTA AESTHETICS",
        system_type="POS",
        system_number="B3D3D9DC50",
        tax_code="VAT15",
        vat_number="43256663343256663322",
        price_vat_inclusive=True,
        region=None, city=None, wereda=None, kebele=None, subcity=None,
        house_number=None, country=None, locality=None, email=None, phone=None,
        default_buyer_id_type="NID",
        default_buyer_id_number="3333367896666",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def single_item(**overrides):
    base = dict(
        item_code="course-id",
        product_description="Item description",
        nature_of_supplies="service",
    )
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# VAT split (the anchor assertion)
# --------------------------------------------------------------------------- #
def test_split_amount_vat15_inclusive_100_etb():
    pre_tax, tax, total = _split_amount(100, "VAT15", vat_inclusive=True)
    assert pre_tax == 86.96
    assert tax == 13.04
    assert total == 100.0


def test_split_amount_vatex_is_zero_tax():
    pre_tax, tax, total = _split_amount(100, "VATEX", vat_inclusive=True)
    assert (pre_tax, tax, total) == (100.0, 0.0, 100.0)


def test_split_amount_exclusive_adds_on_top():
    pre_tax, tax, total = _split_amount(100, "VAT15", vat_inclusive=False)
    assert pre_tax == 100.0
    assert tax == 15.0
    assert total == 115.0


def test_invoice_vat_split_100_etb_vat15():
    inv = build_invoice(
        make_merchant(),
        document_number="1",
        invoice_counter=1,
        previous_irn=None,
        items_or_single=single_item(),
        amount=100,
        now=FIXED_NOW,
    )
    item = inv["ItemList"][0]
    assert item["PreTaxValue"] == 86.96
    assert item["TaxAmount"] == 13.04
    assert item["TotalLineAmount"] == 100.0
    assert inv["ValueDetails"]["TotalValue"] == 100.0
    assert inv["ValueDetails"]["TaxValue"] == 13.04


# --------------------------------------------------------------------------- #
# Contract shape: top-level + item key ORDER (canonical signing depends on it)
# --------------------------------------------------------------------------- #
def test_top_level_keys_in_spec_order():
    inv = build_invoice(
        make_merchant(),
        document_number="1",
        invoice_counter=1,
        previous_irn=None,
        items_or_single=single_item(),
        amount=100,
        now=FIXED_NOW,
    )
    assert list(inv.keys()) == EXPECTED_TOP_LEVEL_ORDER


def test_item_keys_in_spec_order():
    inv = build_invoice(
        make_merchant(),
        document_number="1",
        invoice_counter=1,
        previous_irn=None,
        items_or_single=single_item(),
        amount=100,
        now=FIXED_NOW,
    )
    assert list(inv["ItemList"][0].keys()) == EXPECTED_ITEM_ORDER


def test_document_date_format_and_static_fields():
    inv = build_invoice(
        make_merchant(),
        document_number="7",
        invoice_counter=3,
        previous_irn=None,
        items_or_single=single_item(),
        amount=100,
        now=FIXED_NOW,
    )
    assert inv["DocumentDetails"]["Date"] == "29-06-2026T14:30:00"
    assert inv["DocumentDetails"]["Type"] == "INV"
    assert inv["DocumentDetails"]["DocumentNumber"] == "7"
    assert inv["SourceSystem"]["InvoiceCounter"] == 3
    assert isinstance(inv["SourceSystem"]["InvoiceCounter"], int)
    assert inv["PaymentDetails"]["PaymentTerm"] == "IMMIDIATE"
    assert inv["Version"] == "1"


# --------------------------------------------------------------------------- #
# PreviousIrn: first invoice -> None (serializes to JSON null, spec §7.1)
# --------------------------------------------------------------------------- #
def test_first_previous_irn_is_none():
    inv = build_invoice(
        make_merchant(),
        document_number="1",
        invoice_counter=1,
        previous_irn="",  # falsy -> None
        items_or_single=single_item(),
        amount=100,
        now=FIXED_NOW,
    )
    assert inv["ReferenceDetails"]["PreviousIrn"] is None
    assert inv["ReferenceDetails"]["RelatedDocument"] is None


def test_chained_previous_irn_passes_through():
    inv = build_invoice(
        make_merchant(),
        document_number="2",
        invoice_counter=2,
        previous_irn="test-irn-abc",
        items_or_single=single_item(),
        amount=100,
        now=FIXED_NOW,
    )
    assert inv["ReferenceDetails"]["PreviousIrn"] == "test-irn-abc"


# --------------------------------------------------------------------------- #
# Payment mode default + enum coercion (do-not-inherit #6)
# --------------------------------------------------------------------------- #
def test_payment_mode_defaults_to_cash():
    inv = build_invoice(
        make_merchant(),
        document_number="1",
        invoice_counter=1,
        previous_irn=None,
        items_or_single=single_item(),
        amount=100,
        payment_method="telebirr",  # not a valid Mode enum -> CASH
        now=FIXED_NOW,
    )
    assert inv["PaymentDetails"]["Mode"] == "CASH"


def test_payment_mode_valid_enum_kept():
    inv = build_invoice(
        make_merchant(),
        document_number="1",
        invoice_counter=1,
        previous_irn=None,
        items_or_single=single_item(),
        amount=100,
        payment_method="credit",
        now=FIXED_NOW,
    )
    assert inv["PaymentDetails"]["Mode"] == "CREDIT"


# --------------------------------------------------------------------------- #
# Seller details: Tin + LegalName always; optional only if set
# --------------------------------------------------------------------------- #
def test_seller_details_minimal_when_unset():
    inv = build_invoice(
        make_merchant(),
        document_number="1",
        invoice_counter=1,
        previous_irn=None,
        items_or_single=single_item(),
        amount=100,
        now=FIXED_NOW,
    )
    seller = inv["SellerDetails"]
    # VatNumber is set (needed for VAT15); address fields are unset -> omitted.
    assert list(seller.keys()) == ["Tin", "LegalName", "VatNumber"]
    assert "Region" not in seller


def test_seller_details_includes_set_optionals():
    m = make_merchant(region="1", city="101", email="seller@example.com")
    inv = build_invoice(
        m,
        document_number="1",
        invoice_counter=1,
        previous_irn=None,
        items_or_single=single_item(),
        amount=100,
        now=FIXED_NOW,
    )
    seller = inv["SellerDetails"]
    assert seller["Region"] == "1"
    assert seller["City"] == "101"
    assert seller["Email"] == "seller@example.com"


# --------------------------------------------------------------------------- #
# VAT fail-fast (rule 3.1.4.4): VAT* code with no merchant VatNumber
# --------------------------------------------------------------------------- #
def test_vat_code_without_vat_number_fails_fast():
    m = make_merchant(vat_number=None)
    with pytest.raises(ValueError, match="VAT-prefixed"):
        build_invoice(
            m,
            document_number="1",
            invoice_counter=1,
            previous_irn=None,
            items_or_single=single_item(),
            amount=100,
            now=FIXED_NOW,
        )


def test_non_vat_code_allowed_without_vat_number():
    m = make_merchant(vat_number=None, tax_code="TOT")
    inv = build_invoice(
        m,
        document_number="1",
        invoice_counter=1,
        previous_irn=None,
        items_or_single=single_item(),
        amount=100,
        now=FIXED_NOW,
    )
    item = inv["ItemList"][0]
    assert item["TaxCode"] == "TOT"
    assert item["TaxAmount"] == 0.0
    assert item["TotalLineAmount"] == 100.0


# --------------------------------------------------------------------------- #
# B2C / B2B + registered ID
# --------------------------------------------------------------------------- #
def test_b2c_default_uses_merchant_default_id():
    inv = build_invoice(
        make_merchant(),
        document_number="1",
        invoice_counter=1,
        previous_irn=None,
        buyer={"legal_name": "Customer Name", "email": "buyer@example.com",
               "phone": "+251911223344"},
        items_or_single=single_item(),
        amount=100,
        now=FIXED_NOW,
    )
    assert inv["TransactionType"] == "B2C"
    buyer = inv["BuyerDetails"]
    assert buyer["LegalName"] == "Customer Name"
    assert buyer["Email"] == "buyer@example.com"
    assert buyer["Phone"] == "+251911223344"
    assert buyer["IdType"] == "NID"
    assert buyer["IdNumber"] == "3333367896666"
    assert "Tin" not in buyer


def test_b2b_adds_buyer_tin():
    inv = build_invoice(
        make_merchant(),
        document_number="1",
        invoice_counter=1,
        previous_irn=None,
        buyer={"legal_name": "Acme PLC", "tin": "1234567890"},
        items_or_single=single_item(),
        amount=100,
        now=FIXED_NOW,
    )
    assert inv["TransactionType"] == "B2B"
    assert inv["BuyerDetails"]["Tin"] == "1234567890"


def test_b2b_invalid_tin_fails():
    with pytest.raises(ValueError, match="10 digits"):
        build_invoice(
            make_merchant(),
            document_number="1",
            invoice_counter=1,
            previous_irn=None,
            buyer={"legal_name": "Acme PLC", "tin": "123"},
            items_or_single=single_item(),
            amount=100,
            now=FIXED_NOW,
        )


def test_invalid_buyer_id_type_fails():
    with pytest.raises(ValueError, match="invalid buyer IdType"):
        build_invoice(
            make_merchant(),
            document_number="1",
            invoice_counter=1,
            previous_irn=None,
            buyer={"legal_name": "X", "id_type": "ZZZ", "id_number": "1"},
            items_or_single=single_item(),
            amount=100,
            now=FIXED_NOW,
        )


# --------------------------------------------------------------------------- #
# Phone normalisation (^\+?[0-9]{6,}$): omit, never blank
# --------------------------------------------------------------------------- #
def test_clean_phone_rules():
    assert _clean_phone("+251911223344") == "+251911223344"
    assert _clean_phone("0911 22 33 44") == "0911223344"
    assert _clean_phone("123") is None     # too short
    assert _clean_phone("") is None
    assert _clean_phone(None) is None


def test_invalid_phone_is_omitted_not_blank():
    inv = build_invoice(
        make_merchant(),
        document_number="1",
        invoice_counter=1,
        previous_irn=None,
        buyer={"legal_name": "X", "phone": "12"},  # too short
        items_or_single=single_item(),
        amount=100,
        now=FIXED_NOW,
    )
    assert "Phone" not in inv["BuyerDetails"]


# --------------------------------------------------------------------------- #
# Multi-item invoice: totals sum across lines, LineNumber increments
# --------------------------------------------------------------------------- #
def test_multi_item_totals_and_line_numbers():
    items = [
        single_item(unit_price=100, item_code="a"),
        single_item(unit_price=200, item_code="b"),
    ]
    inv = build_invoice(
        make_merchant(),
        document_number="1",
        invoice_counter=1,
        previous_irn=None,
        items_or_single=items,
        now=FIXED_NOW,
    )
    assert [it["LineNumber"] for it in inv["ItemList"]] == [1, 2]
    # 100 + 200 inclusive -> pretax 86.96 + 173.91, tax 13.04 + 26.09
    assert inv["ValueDetails"]["TotalValue"] == 300.0
    assert inv["ValueDetails"]["TaxValue"] == 39.13


# --------------------------------------------------------------------------- #
# Currency: non-ETB requires exchange_rate
# --------------------------------------------------------------------------- #
def test_non_etb_requires_exchange_rate():
    with pytest.raises(ValueError, match="exchange_rate"):
        build_invoice(
            make_merchant(),
            document_number="1",
            invoice_counter=1,
            previous_irn=None,
            items_or_single=single_item(),
            amount=100,
            currency="USD",
            now=FIXED_NOW,
        )


def test_non_etb_with_exchange_rate_adds_field():
    inv = build_invoice(
        make_merchant(),
        document_number="1",
        invoice_counter=1,
        previous_irn=None,
        items_or_single=single_item(),
        amount=100,
        currency="USD",
        exchange_rate=57.5,
        now=FIXED_NOW,
    )
    assert inv["ValueDetails"]["InvoiceCurrency"] == "USD"
    assert inv["ValueDetails"]["ExchangeRate"] == 57.5
