# MoR EIMS Request Contract — Receipt build spec (source of truth)

Reverse-engineered from the **sandbox-validated** Delta SPMU implementation
(`C:/Users/ASUS/Desktop/Delta_SPMU/backend/frappe-lms/lms/lms/eims.py`, validated
2026-06-12 against `https://core.mor.gov.et` — B2C register + verify + cancel proven,
IRN `test-e191…be34b`) plus `docs/EIMS_INTEGRATION.md` and
`docs/EIMS_CERTIFICATION_GAP_ANALYSIS.md`. **Every implementer in this repo must conform
to this file.** When porting, prefer this spec; it already folds in the Phase-1 fixes.

> Receipt is a **multi-tenant aggregator (BSP)**. The Delta code was single-tenant
> (one set of global config keys). Here, every contract value that was global config in
> Delta becomes **per-merchant** state (TIN, system type/number, certificate, private
> key, API credentials, seller details, tax code, invoice chain). Crypto functions must
> be **pure** — they take the merchant's key/cert as arguments, never read globals.

---

## 0. Transport invariants (EVERY call, including login)

- Body envelope: `{"request": <obj>, "signature": <b64>, "certificate": <b64>}`.
- `signature` = base64( **SHA512withRSA** (RSASSA-PKCS1-v1_5) over the **canonical JSON
  string** of `<obj>` ), using the merchant's private key.
- **Exact-bytes rule:** the canonical string you signed MUST be the exact bytes on the
  wire. Build the envelope by **string interpolation**, never re-serialize `<obj>` through
  a JSON library again (whitespace/reordering breaks server-side verification).
- Canonical JSON: `json.dumps(obj, separators=(",", ":"), ensure_ascii=False)` —
  compact, **no whitespace**, **key order preserved (NOT sorted)**, UTF-8, raw Unicode.
- `certificate` = base64 of the merchant's INSA-issued X.509 PEM chain.
- HTTP: `POST`, `Content-Type: application/json`, `Authorization: Bearer <accessToken>`
  on every call except `/auth/login`, 60s timeout. Body sent as **raw bytes** (`data=`),
  never `json=`.
- Endpoints (appended to merchant base URL): `/auth/login`, `/v1/register`, `/v1/cancel`,
  `/v1/verify`, `/v1/receipt/sales`.
- TLS verify: configurable per environment (sandbox may present a self-signed/IP cert →
  allow `verify=false` in sandbox; `true` in prod).

### Canonical + signing (port verbatim, as pure functions)

```python
def canonical(obj) -> str:
    # compact, no whitespace, key order preserved, UTF-8, ensure_ascii=False
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

def sign(canonical_string: str, private_key) -> str:
    sig = private_key.sign(canonical_string.encode("utf-8"),
                           padding.PKCS1v15(), hashes.SHA512())
    return base64.b64encode(sig).decode()

def certificate_b64(cert_pem: str) -> str:
    if "-----BEGIN CERTIFICATE-----" in cert_pem or "Subject:" in cert_pem:
        return base64.b64encode(cert_pem.encode("utf-8")).decode()
    return cert_pem.strip()  # already base64

def build_signed_body(request_obj, private_key, cert_pem: str) -> bytes:
    c = canonical(request_obj)
    body = '{"request":%s,"signature":%s,"certificate":%s}' % (
        c, json.dumps(sign(c, private_key)), json.dumps(certificate_b64(cert_pem)),
    )
    return body.encode("utf-8")
```

Private key load: PEM from the merchant's stored key (PKCS#8, `password=None`); if no
`-----BEGIN` header, wrap as `-----BEGIN PRIVATE KEY-----\n…\n-----END PRIVATE KEY-----`.

### Optional payload encryption — KEEP OFF

`eims_encrypt_payload` was a best-guess AES-256-CBC (`sha256(encryptionKey)` key,
random 16-byte IV prepended, wrapped `{"data": <b64>}`). The spec **blanks** the real
algorithm; sandbox 2026-06-12 confirmed `/v1/register` needs **no encryption**. Implement
the function but default OFF; do not block on it.

---

## 1. AUTH — `/auth/login`

Request object (sandbox-PROVEN casing 2026-06-12):

```json
{ "clientId": "<client_id>", "clientSecret": "<client_secret>", "apikey": "<api_key>", "tin": "<tin>" }
```

> **Casing caveat:** the auth *schema text* (Draft l.4102-4124) may want all-lowercase
> `clientid`/`clientsecret`/`apikey`/`tin`. camelCase `clientId`/`clientSecret` worked in
> sandbox. **Make the key casing configurable** and add a test that can flip it on 4xx.

Response: `data.accessToken` (required), `data.expiresIn`, `data.encryptionKey` (optional).
Cache token per-merchant with `ttl = max(60, expiresIn - 120)`; fallback 3000s if
`expiresIn` absent. On HTTP 401 for an authed call: drop cached token, re-login (force),
rebuild signed body, POST **once** more.

---

## 2. REGISTER INVOICE — `/v1/register`

Top-level **key order matters** (canonical signing): `TransactionType`, `DocumentDetails`,
`SourceSystem`, `SellerDetails`, `BuyerDetails`, `ItemList`, `PaymentDetails`,
`ValueDetails`, `ReferenceDetails`, `Version`.

```json
{
  "TransactionType": "B2C",
  "DocumentDetails": { "Type": "INV", "DocumentNumber": "1", "Date": "29-06-2026T14:30:00" },
  "SourceSystem": { "SystemType": "POS", "SystemNumber": "B3D3D9DC50", "InvoiceCounter": 1 },
  "SellerDetails": { "Tin": "0107184904", "LegalName": "DELTA AESTHETICS" },
  "BuyerDetails": {
    "LegalName": "Customer Name", "Email": "buyer@example.com", "Phone": "+251911223344",
    "IdType": "NID", "IdNumber": "3333367896666"
  },
  "ItemList": [{
    "LineNumber": 1, "NatureOfSupplies": "service", "ItemCode": "course-id",
    "ProductDescription": "Item description", "Unit": "PCS", "UnitPrice": 86.96,
    "Quantity": 1, "Discount": 0, "PreTaxValue": 86.96, "ExciseTaxValue": 0,
    "TaxCode": "VAT15", "TaxAmount": 13.04, "TotalLineAmount": 100.0
  }],
  "PaymentDetails": { "PaymentTerm": "IMMIDIATE", "Mode": "CASH" },
  "ValueDetails": {
    "TotalValue": 100.0, "TaxValue": 13.04, "ExciseValue": 0,
    "TransactionWithholdValue": 0, "IncomeWithholdValue": 0, "InvoiceCurrency": "ETB"
  },
  "ReferenceDetails": { "PreviousIrn": null, "RelatedDocument": null },
  "Version": "1"
}
```

### Field rules / enums (all sandbox-confirmed unless noted)

- **TransactionType**: `"B2C"` (default, no buyer TIN) or `"B2B"` (set when buyer TIN
  present → add `"Tin"` to BuyerDetails).
- **DocumentDetails.Type** `"INV"`; **Date** = `dd-MM-yyyy'T'HH:mm:ss` → Python
  `"%d-%m-%YT%H:%M:%S"`.
- **SourceSystem.InvoiceCounter**: integer (not string). SystemType/SystemNumber strings.
- **SellerDetails (exact-match rule, error 7017):** send ONLY `Tin` + `LegalName`
  unconditionally. **⚠ 2026-07-06: `Wereda` is schema-REQUIRED (error 1028) — it cannot be
  omitted; it must be sent with MoR's recorded value. Delta sandbox-proven seller block =
  Tin + LegalName + VatNumber + Region "1" + City "101" + Wereda "13" and NOTHING else.** Optional fields (`VatNumber, Region, City, Wereda, Kebele, SubCity,
  HouseNumber, Country, Locality, Email, Phone`) sent ONLY when stored for the merchant AND
  confirmed to match MoR's record exactly; omitted ones are auto-filled by MoR.
- **BuyerDetails:** `LegalName` always. `Email` only if non-empty. `Phone` only if it
  matches `^\+?[0-9]{6,}$` (normalize; omit, never blank). **B2C registered-ID (error
  7004):** must send `IdType` + `IdNumber`; valid `IdType` enum: `NID, KID, SID, WID, PST,
  DLS, MRS`. B2B: add `"Tin"`.
- **ItemList** per-line, exactly these 13 keys in this order: `LineNumber`(int),
  `NatureOfSupplies` (LOWERCASE enum `"goods"`/`"service"`, error 7025), `ItemCode`(≤15),
  `ProductDescription`(≤300), `Unit`(`"PCS"`), `UnitPrice`, `Quantity`, `Discount`,
  `PreTaxValue`, `ExciseTaxValue`, `TaxCode`, `TaxAmount`, `TotalLineAmount`.
- **PaymentDetails.Mode** ∈ {`CASH`, `ADVANCE`, `CREDIT`} — default **CASH** (see
  do-not-inherit #6). `PaymentTerm` = `"IMMIDIATE"` [sic].
- **ValueDetails:** the 6 fields above; add `"ExchangeRate": <float>` only when
  `InvoiceCurrency != "ETB"`.
- **ReferenceDetails.PreviousIrn** = previous IRN, or JSON **`null`** for the first
  invoice (NEVER `""`). `RelatedDocument` = `null` for plain invoices.
- **Version** = string `"1"`.
- **VAT math (rule 3.1.4.4):** any VAT-prefixed TaxCode (`VAT0/VAT15/VATEX`) REQUIRES
  `SellerDetails.VatNumber` (errors 7024/7029/7017). Fail fast if a VAT* code is used with
  no merchant VAT number. VAT-inclusive split: `pre_tax = round(amount/(1+rate/100), 2)`;
  100 ETB @ VAT15 → PreTax 86.96 + Tax 13.04. VATEX → `TaxAmount: 0`.

### Success response (read path)

`statusCode == 200`, `body = resp["body"]`: keys `irn`, `documentNumber`, `ackDate`,
`signedQR` (base64 PNG), `signedInvoice` (signed blob). Persist all; advance the
**per-merchant** chain (counter + last_irn = `body.irn`) **only on success**.

---

## 3. CANCEL / VERIFY

- Cancel `/v1/cancel`: `{ "Irn": "<irn>", "ReasonCode": "3", "Remark": "<text>" }`.
  ReasonCode is a single char string `1`=Duplicate, `2`=Data-entry mistake,
  `3`=Order Cancelled, `4`=Others — **validate it's in {1,2,3,4}**. Success when
  `statusCode==200` or `status=="success"`. **Persist MoR's returned `cancelationDate`**,
  not local time.
- Verify `/v1/verify`: `{ "irn": "<irn>" }` — note **lowercase `irn`** here (vs capital
  `Irn` in cancel).

---

## 4. CREDIT / DEBIT NOTES — chained via `/v1/register`

Start from the invoice builder, then mutate:
`DocumentDetails.Type` = `"CRE"`/`"DEB"`, `DocumentDetails.Reason` = text (≤300, MANDATORY),
`ReferenceDetails.RelatedDocument` = **the original invoice's IRN string** (sandbox-proven —
NOT the document number, else 7020/7030). Notes get their own IRN + counter (same chain).
CRE guard: credit `TotalValue` must not exceed original + 0.005.

---

## 5. SALES RECEIPT — `/v1/receipt/sales`  ✅ SANDBOX-VALIDATED 2026-07-06 (RRN test-f19e…2089 — first ever on this stack; Delta never proved this path)

Date format **differs** from invoices: `RECEIPT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.000+03:00"`.
Not chained. Success reads `body.rrn` (Receipt Reference Number).

```json
{
  "ReceiptNumber": "REC-<tx>", "ReceiptType": "Sales Receipts", "Reason": "...",
  "ReceiptDate": "2026-06-29T14:30:00.000+03:00", "ReceiptCounter": "<current counter>",
  "SourceSystemType": "POS", "SourceSystemNumber": "B3D3D9DC50", "ReceiptCurrency": "ETB",
  "ExchangeRate": null, "CollectedAmount": 100.0, "SellerTIN": "0107184904",
  "Invoices": [{ "InvoiceIRN": "<irn>", "PaymentCoverage": "FULL",
                 "InvoicePaidAmount": 100.0, "TotalAmount": 100.0 }],
  "TransactionDetails": { "ModeOfPayment": "CASH", "CollectorName": "...",
    "PaymentServiceProvider": "...", "AccountNumber": "...", "TransactionNumber": "..." }
}
```

> VALIDATED: this exact shape returned a real RRN on 2026-07-06. Guard: refuse a receipt
> against a **cancelled** invoice.

---

## 6. Data model (multi-tenant — Postgres)

- `merchants(id, tin UNIQUE, legal_name, system_type, system_number, base_url,
  tax_code, vat_number, price_vat_inclusive, region, city, wereda, kebele, subcity,
  house_number, country, locality, email, phone, default_buyer_id_type,
  default_buyer_id_number, tls_verify, encrypt_payload, status, created_at)`
- `merchant_secrets(merchant_id, client_id, client_secret, api_key,
  private_key_ref, certificate_ref)` — values resolved from the **secrets backend**
  (AWS Secrets Manager in cloud; env/.env for local). NEVER store plaintext key/secret in
  the DB; store references.
- `invoice_chain(merchant_id PK, counter, last_irn)` — chain head, one row per merchant.
- `documents(id, merchant_id, doc_type, transaction_ref, document_number, irn, rrn,
  fiscal_status, qr_b64, signed_invoice, ack_date, cancelation_date, error, retry_count,
  amount, currency, buyer_tin, payload_json, created_at, registered_at)` — idempotent on
  `(merchant_id, transaction_ref)`; `fiscal_status` ∈ `Not Registered/Pending/Registered/
  Failed/Cancelled`.

Concurrency: serialize each merchant's chain with a **Postgres advisory lock** keyed by the
merchant TIN (`pg_advisory_xact_lock(hashtext('receipt_register:'||tin))`), the analogue
of Delta's MariaDB `GET_LOCK`. Idempotent: a `(merchant, transaction_ref)` gets at most one
IRN; advance chain only on success.

---

## 7. DO-NOT-INHERIT (defects the new build must already be correct on)

1. First-invoice `PreviousIrn` must serialize to JSON **`null`**, never `""`.
2. Auth key casing configurable (don't hard-depend on camelCase).
3. Sales-receipt: full 12-field schema; success reads **`body.rrn`** (not `irn`).
4. CRE/DEB: set `DocumentDetails.Reason`; `RelatedDocument` = original **IRN string**;
   enforce credit ≤ original.
5. Guard receipts/notes against **cancelled** invoices (cancel must flag the doc).
6. `PaymentDetails.Mode` default **`CASH`** — never `"Direct Transfer"` (invalid enum).
7. Cancel: validate `ReasonCode ∈ {1,2,3,4}`; persist MoR's returned `cancelationDate`.
8. B2B: validate buyer TIN (10-digit) + non-empty LegalName before send.

---

## 8. Delta = merchant #1 (seed values)

Non-secret (from `Delta_SPMU/scripts/configure-eims.sh`): `system_type=POS`,
`system_number=B3D3D9DC50`, `legal_name="DELTA AESTHETICS"`, `tin=0107184904`,
`tax_code=VAT15`, `region=1`, `city=101`, `wereda=11`, `kebele="Near Bole Airport"`,
`house_number=123B`, `country=1`, `email=Deltaspmu@gmail.com`, `phone=251951777888`,
`price_vat_inclusive=true`. **Secrets to be supplied** (from Delta EC2
`site_config.json` + `/home/frappe/deltaspmu/eims/`): `client_id`, `client_secret`,
`api_key`, `vat_number` (sandbox seed `43256663343256663322`), `base_url` (sandbox host),
`private_key.key`, `certificate.pem`, sandbox default buyer `IdType=NID`/
`IdNumber=3333367896666`. Until supplied, the sandbox smoke test cannot authenticate.

## Line-item & note validation rules (sandbox-observed 2026-07-06/07, encoded in `invoice_builder.py` / `webapp.py`)

Learned from live rejections; all now enforced by the builder:

1. **Per-field reconstruction, exact match.** The gateway recomputes each line
   from the *sent* `UnitPrice`: `TotalLineAmount == UnitPrice·Qty·(1+rate)` and
   `TaxAmount == UnitPrice·Qty·rate`, each quantized HALF_UP **to the same
   number of decimals as the sent UnitPrice**, compared exactly. Evidence:
   `expected 80.01 received 80.0` (2dp unit), `expected 2999.9999 received
   3000.0` (4dp unit), `taxAmount expected 26.0870 received 26.09` (4dp unit).
2. **Consequence:** send 2dp units and cent-search the unit whose
   reconstruction lands on the charged amount; skip candidates whose products
   hit an exact `.005` tie (MoR's tie-break rounding is unknown — HALF_UP vs
   HALF_EVEN would disagree). Some stickers are unreachable (80.00 @ VAT15) —
   accept ≤0.02 drift. Fuzzed 2006 price×qty cases: 0 ambiguous.
3. **B2B buyer must exist**: unknown buyer TIN → `BUYER_TIN: (null) false :
   buyer not found 503`. Sandbox: Delta's own TIN works as buyer.
4. **Credit/debit notes must mirror the original invoice**: same items
   (error 7020 "Item mismatch") **and** same transaction type/buyer
   (error 7030 "Transaction type does not match"). Rebuild note items from the
   original payload's ItemList and carry over BuyerDetails.
5. **Portal UX traps** (not API issues): Invoice Report lists oldest-first
   (newest docs on the last page); RRNs live under the separate Receipt
   report; IRNs copied from wrapped UI text may contain line-breaks that
   break the portal's exact-match IRN search. `/v1/verify` is authoritative.
