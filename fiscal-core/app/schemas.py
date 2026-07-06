"""Pydantic v2 request/response DTOs for the Receipt fiscal-core API.

These are the wire shapes for OUR service's HTTP API (what callers POST to
Receipt), NOT the MoR EIMS envelope shapes — those canonical bodies are built
in the request builders from merchant state + these inputs. Field rules echo
MOR_EIMS_CONTRACT.md §1-§5 (enums, id types, reason codes).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Enum aliases mirroring the contract (spec §2/§3).
IdType = Literal["NID", "KID", "SID", "WID", "PST", "DLS", "MRS"]
NatureOfSupplies = Literal["goods", "service"]
PaymentMode = Literal["CASH", "ADVANCE", "CREDIT"]
TransactionType = Literal["B2C", "B2B"]
CancelReasonCode = Literal["1", "2", "3", "4"]
DocType = Literal["INV", "CRE", "DEB"]


# --------------------------------------------------------------------------- #
# Merchant onboarding
# --------------------------------------------------------------------------- #
class MerchantSecretCreate(BaseModel):
    """Credential REFERENCES supplied at merchant creation (never plaintext)."""

    client_id: Optional[str] = None
    client_secret: Optional[str] = Field(default=None, description="Reference, not plaintext")
    api_key: Optional[str] = Field(default=None, description="Reference, not plaintext")
    private_key_ref: Optional[str] = None
    certificate_ref: Optional[str] = None


class MerchantCreate(BaseModel):
    """Create a tenant. Mirrors Merchant model columns (spec §6)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    tin: str
    legal_name: str
    system_type: Optional[str] = None
    system_number: Optional[str] = None
    base_url: Optional[str] = None
    tax_code: Optional[str] = None
    vat_number: Optional[str] = None
    price_vat_inclusive: bool = True

    region: Optional[str] = None
    city: Optional[str] = None
    wereda: Optional[str] = None
    kebele: Optional[str] = None
    subcity: Optional[str] = None
    house_number: Optional[str] = None
    country: Optional[str] = None
    locality: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

    default_buyer_id_type: Optional[IdType] = None
    default_buyer_id_number: Optional[str] = None

    tls_verify: bool = True
    encrypt_payload: bool = False
    status: str = "active"

    secret: Optional[MerchantSecretCreate] = None


class MerchantResponse(BaseModel):
    """Tenant view (no secrets ever returned)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tin: str
    legal_name: str
    system_type: Optional[str] = None
    system_number: Optional[str] = None
    base_url: Optional[str] = None
    tax_code: Optional[str] = None
    vat_number: Optional[str] = None
    price_vat_inclusive: bool
    status: str


# --------------------------------------------------------------------------- #
# Register invoice
# --------------------------------------------------------------------------- #
class InvoiceItem(BaseModel):
    """One sale line. Tax split is computed by the builder; raw inputs here."""

    nature_of_supplies: NatureOfSupplies = "service"
    item_code: str = Field(max_length=15)
    product_description: str = Field(max_length=300)
    unit: str = "PCS"
    unit_price: float
    quantity: float = 1
    discount: float = 0
    tax_code: Optional[str] = Field(default=None, description="Overrides merchant tax_code")


class BuyerDetails(BaseModel):
    """Optional buyer block. Presence of ``tin`` implies B2B."""

    legal_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    id_type: Optional[IdType] = None
    id_number: Optional[str] = None
    tin: Optional[str] = Field(default=None, description="10-digit buyer TIN -> B2B")


class RegisterInvoiceRequest(BaseModel):
    """Register a fiscal invoice for a merchant."""

    model_config = ConfigDict(str_strip_whitespace=True)

    merchant_tin: str
    transaction_ref: str = Field(description="Idempotency key per merchant")
    doc_type: DocType = "INV"

    currency: str = "ETB"
    exchange_rate: Optional[float] = None  # required by builder when currency != ETB
    payment_mode: PaymentMode = "CASH"

    buyer: Optional[BuyerDetails] = None
    items: list[InvoiceItem] = Field(min_length=1)

    # CRE/DEB chaining (spec §4).
    related_irn: Optional[str] = Field(default=None, description="Original IRN for CRE/DEB")
    reason: Optional[str] = Field(default=None, max_length=300, description="Mandatory for CRE/DEB")


# --------------------------------------------------------------------------- #
# Cancel / Verify
# --------------------------------------------------------------------------- #
class CancelRequest(BaseModel):
    """Cancel an invoice (spec §3). ReasonCode validated to {1,2,3,4}."""

    irn: str
    reason_code: CancelReasonCode = "3"
    remark: Optional[str] = None


class VerifyRequest(BaseModel):
    """Verify an invoice by IRN (spec §3 — lowercase ``irn`` on the wire)."""

    irn: str


# --------------------------------------------------------------------------- #
# Sales receipt (spec §5 — coded, sandbox-unvalidated)
# --------------------------------------------------------------------------- #
class ReceiptInvoiceRef(BaseModel):
    """An invoice covered by a sales receipt."""

    invoice_irn: str
    payment_coverage: str = "FULL"
    invoice_paid_amount: float
    total_amount: float


class ReceiptTransactionDetails(BaseModel):
    """Payment metadata for a sales receipt."""

    mode_of_payment: PaymentMode = "CASH"
    collector_name: Optional[str] = None
    payment_service_provider: Optional[str] = None
    account_number: Optional[str] = None
    transaction_number: Optional[str] = None


class ReceiptRequest(BaseModel):
    """Create a sales receipt (spec §5). Success reads ``body.rrn``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    merchant_tin: str
    transaction_ref: str
    receipt_type: str = "Sales Receipts"
    reason: Optional[str] = None
    currency: str = "ETB"
    exchange_rate: Optional[float] = None
    collected_amount: float
    invoices: list[ReceiptInvoiceRef] = Field(min_length=1)
    transaction_details: ReceiptTransactionDetails = Field(default_factory=ReceiptTransactionDetails)


# --------------------------------------------------------------------------- #
# Generic fiscal response DTO
# --------------------------------------------------------------------------- #
class FiscalDocumentResponse(BaseModel):
    """Outcome of a register/cancel/verify/receipt call."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant_id: int
    doc_type: str
    transaction_ref: str
    document_number: Optional[str] = None
    irn: Optional[str] = None
    rrn: Optional[str] = None
    fiscal_status: str
    qr_b64: Optional[str] = None
    signed_invoice: Optional[str] = None
    ack_date: Optional[str] = None
    cancelation_date: Optional[str] = None
    error: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    buyer_tin: Optional[str] = None
