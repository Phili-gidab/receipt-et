"""SQLAlchemy 2.0 ORM models — multi-tenant fiscal data model (spec §6).

Mirrors MOR_EIMS_CONTRACT.md §6 exactly:

  * Merchant         — per-tenant fiscal identity & seller details. Every value
                       that was global config in Delta lives here.
  * MerchantSecret   — REFERENCES (not plaintext) to credentials/key/cert; the
                       actual values are resolved via app.secrets_backend.
  * InvoiceChain     — one row per merchant; the chain head (counter, last_irn).
  * Document         — one fiscal document; idempotent on
                       (merchant_id, transaction_ref); fiscal_status enum.

Concurrency: each merchant's chain is serialized with a Postgres advisory lock
keyed by TIN (see app.db.pg_advisory_xact_lock); the chain is advanced only on
a successful register.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class FiscalStatus(str, enum.Enum):
    """Document fiscal lifecycle (spec §6)."""

    NOT_REGISTERED = "Not Registered"
    PENDING = "Pending"
    REGISTERED = "Registered"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


# Reuse a single Enum type instance so both the column and code share the values.
fiscal_status_enum = Enum(
    FiscalStatus,
    name="fiscal_status",
    values_callable=lambda e: [m.value for m in e],
    native_enum=True,
)


class Merchant(Base):
    """A tenant (BSP merchant). Holds all per-merchant fiscal/seller values."""

    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Fiscal identity.
    tin: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    system_type: Mapped[str | None] = mapped_column(String(32))      # e.g. "POS"
    system_number: Mapped[str | None] = mapped_column(String(64))    # e.g. "B3D3D9DC50"
    base_url: Mapped[str | None] = mapped_column(String(512))        # merchant API base
    tax_code: Mapped[str | None] = mapped_column(String(32))         # e.g. "VAT15"
    vat_number: Mapped[str | None] = mapped_column(String(64))       # required for VAT* codes

    # Pricing behaviour.
    price_vat_inclusive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Seller address / contact (optional; exact-match rule, spec §2 error 7017).
    region: Mapped[str | None] = mapped_column(String(64))
    city: Mapped[str | None] = mapped_column(String(64))
    wereda: Mapped[str | None] = mapped_column(String(64))
    kebele: Mapped[str | None] = mapped_column(String(64))
    subcity: Mapped[str | None] = mapped_column(String(64))
    house_number: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str | None] = mapped_column(String(64))
    locality: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))

    # Default buyer identity for B2C registered-ID (spec §2 error 7004).
    default_buyer_id_type: Mapped[str | None] = mapped_column(String(8))    # NID/KID/...
    default_buyer_id_number: Mapped[str | None] = mapped_column(String(64))

    # Transport toggles.
    tls_verify: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    encrypt_payload: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    secret: Mapped[MerchantSecret | None] = relationship(
        back_populates="merchant", uselist=False, cascade="all, delete-orphan"
    )
    chain: Mapped[InvoiceChain | None] = relationship(
        back_populates="merchant", uselist=False, cascade="all, delete-orphan"
    )
    documents: Mapped[list[Document]] = relationship(
        back_populates="merchant", cascade="all, delete-orphan"
    )


class MerchantSecret(Base):
    """Credential REFERENCES for a merchant — never plaintext key/secret.

    ``private_key_ref`` / ``certificate_ref`` and the credential fields are
    resolved through app.secrets_backend (env files or AWS Secrets Manager).
    """

    __tablename__ = "merchant_secrets"

    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), primary_key=True
    )
    client_id: Mapped[str | None] = mapped_column(String(255))
    client_secret: Mapped[str | None] = mapped_column(String(255))   # reference, not plaintext
    api_key: Mapped[str | None] = mapped_column(String(255))         # reference, not plaintext
    private_key_ref: Mapped[str | None] = mapped_column(String(512))
    certificate_ref: Mapped[str | None] = mapped_column(String(512))

    merchant: Mapped[Merchant] = relationship(back_populates="secret")


class InvoiceChain(Base):
    """Per-merchant invoice chain head (one row per merchant)."""

    __tablename__ = "invoice_chain"

    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), primary_key=True
    )
    counter: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_irn: Mapped[str | None] = mapped_column(String(255))

    merchant: Mapped[Merchant] = relationship(back_populates="chain")


class TelegramAccount(Base):
    """A Telegram user linked to a merchant (bot login).

    One row per Telegram user; created by the bot's phone+OTP link flow and
    deleted by /unlink. ``create_all`` adds the table on startup — no ALTER of
    existing tables, so it is safe on the deployed EC2 database.
    """

    __tablename__ = "telegram_accounts"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    merchant: Mapped[Merchant] = relationship()


class Document(Base):
    """A single fiscal document. Idempotent on (merchant_id, transaction_ref)."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("merchant_id", "transaction_ref", name="uq_documents_merchant_txref"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    doc_type: Mapped[str] = mapped_column(String(8), nullable=False, default="INV")  # INV/CRE/DEB
    transaction_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    document_number: Mapped[str | None] = mapped_column(String(64))
    irn: Mapped[str | None] = mapped_column(String(255), index=True)
    rrn: Mapped[str | None] = mapped_column(String(255))   # sales-receipt reference number

    fiscal_status: Mapped[FiscalStatus] = mapped_column(
        fiscal_status_enum, nullable=False, default=FiscalStatus.NOT_REGISTERED
    )

    qr_b64: Mapped[str | None] = mapped_column(Text)          # base64 PNG (signedQR)
    signed_invoice: Mapped[str | None] = mapped_column(Text)  # signed blob

    ack_date: Mapped[str | None] = mapped_column(String(64))         # MoR-returned ackDate
    cancelation_date: Mapped[str | None] = mapped_column(String(64))  # MoR-returned (spec §3)

    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(8))
    buyer_tin: Mapped[str | None] = mapped_column(String(32))

    payload_json: Mapped[str | None] = mapped_column(Text)   # canonical request sent

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    merchant: Mapped[Merchant] = relationship(back_populates="documents")


class Product(Base):
    """A catalog item, stored MoR-correct (spec §2 ItemList field rules).

    ``code`` is the MoR ItemCode (≤15 chars), ``nature`` the lowercase
    NatureOfSupplies enum ("goods"/"service", error 7025), ``tax_code`` an
    optional per-item override of the merchant default (VAT15/VAT0/VATEX).
    ``stock_qty`` NULL means stock is not tracked for this item; tracked stock
    is decremented in the shared checkout path and may go negative (oversell
    shows up instead of being silently clamped). ``create_all`` adds the table
    on next seed/bot run — no ALTER of existing tables.
    """

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("merchant_id", "code", name="uq_products_merchant_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    code: Mapped[str] = mapped_column(String(15), nullable=False)      # MoR ItemCode
    name: Mapped[str] = mapped_column(String(300), nullable=False)     # ProductDescription
    nature: Mapped[str] = mapped_column(String(8), nullable=False, default="goods")  # goods/service
    tax_code: Mapped[str | None] = mapped_column(String(32))           # None → merchant default
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    stock_qty: Mapped[float | None] = mapped_column(Numeric(18, 3))    # None = untracked
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    merchant: Mapped[Merchant] = relationship()


class Buyer(Base):
    """A saved B2B buyer (name + TIN) for the merchant's directory.

    ``proven`` flips to True the first time a registration with this TIN
    succeeds at MoR — the directory doubles as a list of TINs known to exist
    in MoR's registry (spec §8.3: unknown buyer TIN → "buyer not found 503").
    Rows are auto-upserted by the shared checkout path on successful B2B sales.
    """

    __tablename__ = "buyers"
    __table_args__ = (
        UniqueConstraint("merchant_id", "tin", name="uq_buyers_merchant_tin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tin: Mapped[str] = mapped_column(String(32), nullable=False)
    proven: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    merchant: Mapped[Merchant] = relationship()
