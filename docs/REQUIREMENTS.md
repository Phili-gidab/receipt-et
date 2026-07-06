# Receipt — Software Requirements (SRS)

Requirements for **Receipt (ደረሰኝ)**, a SaaS cloud-POS + electronic fiscal-receipt
product for Ethiopian businesses, equivalent in scope to **slip.et** and
**deresegn.et**, built on top of the sandbox-validated MoR EIMS fiscal core.

**Sources:** MoR `MoR_BSP_Master` compliance checklist; MoR *Guide to Generating and
Using Certificate for E-Invoicing*; MoR Commitment Form; Bank guarantee template; INSA
cert-request form; buyer/government test lists; slip.et product reference; the
sandbox-validated contract in [`MOR_EIMS_CONTRACT.md`](MOR_EIMS_CONTRACT.md); the
`Receipt-landing` marketing site. *(Delta SPMU e-invoice sandbox integration confirmed
working; test credentials to be supplied.)*

> Status legend: **[MVP]** first release · **[V2]** fast-follow · **[LATER]** post-launch.

---

## 1. Vision & positioning
Ethiopia is moving from paper receipts to MoR-validated, QR-coded electronic invoices
(Directive 188; VAT proclamation). Receipt lets any business issue an MoR-compliant,
signed, QR fiscal receipt on **every sale — online or offline — from a phone/tablet they
already own**, with no dedicated fiscal machine. Receipt is the **BSP/aggregator** behind
the app: each merchant's TIN, INSA certificate, and MoR source-system credentials are
configured once, and Receipt signs + registers every document with EIMS on their behalf.

## 2. Actors & roles
- **Owner** — signs the business up, completes onboarding (TIN, VAT, MoR creds, cert),
  manages staff, sees all reports/branches.
- **Cashier / Seller** — rings up sales, issues receipts, refunds/voids within permission;
  secured by a personal PIN.
- **Manager (branch)** — cashier rights + branch reports **[V2]**.
- **Platform admin (Receipt staff)** — onboards merchants, manages per-merchant secrets,
  monitors health; never sees other tenants' plaintext keys.
- **Buyer** — receives the receipt (print / SMS / email / digital), can verify via MoR.
- **MoR EIMS / INSA** — external fiscal + certificate authorities.

## 3. Functional requirements

### FR-A · Onboarding & authentication  [MVP]
- FR-A1 Sign up / sign in by **Ethiopian phone number + SMS OTP** (slip.et parity); session
  persisted; optional 6-digit PIN per user.
- FR-A2 Business onboarding wizard: business legal name, **TIN (10-digit)**, VAT number,
  address (region/city/wereda/kebele), contact. *(V2: OCR "scan your VAT certificate".)*
- FR-A3 **Connect to MoR**: capture the merchant's EIMS **client id / client secret / API
  key**, **system type + system number**, base URL, and upload **private key + INSA
  certificate** — stored as references in the secrets backend, never plaintext (see NFR-SEC).
- FR-A4 Guided assistance for taxpayers requesting MoR e-invoicing credentials + the INSA
  certificate (CSR generation help) **[V2]**.

### FR-B · Merchant / tenant configuration  [MVP]
- FR-B1 Per-merchant fiscal identity: TIN, legal name, system type/number, tax code
  (VAT15/VAT0/VATEX), VAT number, price-VAT-inclusive flag, default buyer id, TLS/encrypt
  toggles, seller address (exact-match rule, EIMS error 7017).
- FR-B2 **Multi-branch / sub-TIN** management; every document traceable to merchant + branch
  (MoR Section C traceability) **[V2]**.
- FR-B3 Plan/subscription tier (Starter free / Business / Multi-branch) gating features.

### FR-C · Point of sale (sell)  [MVP]
- FR-C1 Cart: add catalogue items or free items (name, qty, unit price, discount); running
  subtotal, VAT (15%), total; VAT-inclusive pricing.
- FR-C2 Tenders: **cash, card, telebirr / mobile money**; split tender; change due.
- FR-C3 **3% domestic withholding** on qualifying B2B sales, computed and shown.
- FR-C4 B2C (walk-in, default buyer id) and **B2B** (buyer TIN + legal name) sales.
- FR-C5 Fast, touch-first UI usable one-handed on a phone; Amharic + English.

### FR-D · Fiscal registration (the compliance core)  [MVP]
Maps directly to the MoR BSP Master IRC test cases and the validated contract:
- FR-D1 **Register B2C invoice** with VAT, print IRN + QR — *IRC-P01*.
- FR-D2 **Register B2B invoice** with buyer TIN + legal name, discounts/excise/withholding —
  *IRC-P02*; reject invalid/unregistered buyer TIN — *IRC-N08*.
- FR-D3 **Register sales receipt** against a registered invoice → RRN — *IRC-P03*; reject
  receipt for non-existent/cancelled invoice — *IRC-N09*.
- FR-D4 **Register withholding receipt** — *IRC-P04* **[V2]**.
- FR-D5 **Credit memo** (≤ original) and **Debit memo** against a registered invoice —
  *IRC-P06 / IRC-P07*; `RelatedDocument` = original IRN.
- FR-D6 **Cancel** a registered invoice (reason 1-4), persist MoR cancelationDate — *IRC-P05*;
  reject cancel of non-existent/already-cancelled — *IRC-N010*.
- FR-D7 Each merchant keeps an **ordered invoice chain** (counter + PreviousIrn), advanced
  only on success, serialized per merchant, **idempotent** per transaction.
- FR-D8 Signing/transport exactly per [`MOR_EIMS_CONTRACT.md`](MOR_EIMS_CONTRACT.md)
  (envelope, canonical JSON, SHA512withRSA, endpoints).

### FR-E · Printing, QR & delivery  [MVP]  (*ADD-P001*)
- FR-E1 Render compliant receipt in **thermal 58/80 mm** and **A4**, with seller (name/TIN/
  VAT), buyer, itemised lines, VAT/withholding, total, **IRN, signed QR**, and amount-in-words.
- FR-E2 Print to any thermal or normal printer; **PDF**; **shareable digital receipt**.
- FR-E3 Buyer QR is scannable and verifiable through MoR's verification service.

### FR-F · Offline / contingency mode  [V2] (slip.et headline; PWA)
- FR-F1 Issue + save a sale with **zero connectivity**; give the buyer a contingency QR.
- FR-F2 Queue on device; **auto-sync in order** to MoR when back online; nothing lost.
- FR-F3 No document stuck on a single terminal (server-reconciled).

### FR-G · Inventory  [V2]
Products, categories, prices, stock levels, low-stock alerts, quick ring-up.

### FR-H · Team & access control  [MVP core, V2 full]  (*ADD-C001 / Setup & Config*)
- FR-H1 Add employees, assign **roles** (owner/manager/cashier/viewer), per-till **PIN**.
- FR-H2 **Least privilege**: only admins configure credentials/keys; other roles cannot
  view/modify secrets; secrets entered at runtime, stored encrypted, not in source.

### FR-I · Reports & dashboard  [MVP dashboard, V2 full]
- FR-I1 Live sales dashboard (today's sales, count, VAT).
- FR-I2 Daily **Z-report**, **VAT report**, withholding report, per-branch/consolidated **[V2]**.
- FR-I3 Searchable **receipt history**: search, reprint, refund, void, long retention.

### FR-J · Notifications  [V2]  (*ADD-N001*)
SMS + email to the buyer on registration/cancellation/debit/credit/receipt/withholding,
within 5 min, stating action, date/time, document number, reason.

### FR-K · Multi-tenant / aggregator  [MVP]  (MoR **Section C**)
- FR-K1 Strict per-merchant data isolation; no cross-tenant leakage.
- FR-K2 Per-merchant encryption of keys/credentials; per-merchant rate handling (one big
  merchant can't starve others) **[V2]**.
- FR-K3 Per-merchant dashboards/alerts; exit/data-export per merchant **[V2]**.

## 4. Non-functional requirements

- **NFR-PERF** Invoice/receipt registration API < 2 s per call; UI usable on a **2 Mbps**
  link → server-rendered lightweight pages, minimal JS, compressed assets, lazy media,
  small payloads (this is the primary design constraint of the Ethio Telecom host).
- **NFR-SCALE** ≥ 50 concurrent users; many merchants; horizontal-ready.
- **NFR-SEC** (INSA) HTTPS/TLS everywhere; credentials/keys **encrypted at rest**, never
  hard-coded, entered at runtime, admin-only; **RBAC**; **audit logs ≥ 90 days**; OWASP /
  VA + pen-test clean; IMDSv2/host hardening.
- **NFR-REL** Automatic retry of failed registrations; daily backup + tested restore;
  monitoring + alerts; health check; DR plan/diagram.
- **NFR-AVAIL** SLA ≥ 99.5 % (Section H); graceful degradation to offline mode.
- **NFR-RESIDENCY** Data hosted **in Ethiopia** (Ethio Telecom Linux server) for MoR/INSA
  residency; containerized for portability.
- **NFR-USE** Amharic + English UI; Ethiopian + Gregorian dates; ETB; low-literacy-friendly;
  mobile-first.
- **NFR-PORT** Dockerized; deployable to a single Linux VPS via `docker compose`.

## 5. Integration & cryptography  (from cert guideline + validated contract)
- Envelope `{request, signature, certificate}` on **every** call incl. login.
- `signature` = base64(**SHA512withRSA**, PKCS1v15) over the **canonical JSON** string
  (compact, key-order-preserved, UTF-8) — **exact bytes** on the wire.
- `certificate` = base64 of the INSA X.509 PEM chain; private key PKCS#8.
- Endpoints: `/auth/login`, `/v1/register`, `/v1/cancel`, `/v1/verify`, `/v1/receipt/sales`.
- Full field rules, enums, date formats, VAT math, and the DO-NOT-INHERIT defect list are
  authoritative in [`MOR_EIMS_CONTRACT.md`](MOR_EIMS_CONTRACT.md).

## 6. Compliance & certification (to become a provider)
- INSA digital certificate per system (CSR → `ica@insa.gov.et`).
- MoR source-system approval → client id/secret/API key + system number.
- Pass the **MoR BSP Master** checklist in sandbox (IRC-P01..P07, IRC-N08..N010, ADD-*),
  as an **Aggregator (Section C)** + Section A non-functional items; evidence = IRNs/RRNs +
  printouts + QR scans.
- INSA web-app security audit (OWASP/VA/pen-test).
- Signed **Commitment Form** (2-working-day onboarding SLA).
- **Bank guarantee USD 30,000** (2-yr renewable).
- See [`CERTIFICATION_PLAN.md`](CERTIFICATION_PLAN.md) for the step-by-step path + case map.

## 7. Data entities (high level)
Merchant · MerchantSecret (refs) · Branch **[V2]** · User(role,PIN) · InvoiceChain ·
Product **[V2]** · Sale/Cart · Document(INV/RCP/CRE/DEB; irn/rrn/qr/status/chain) ·
Payment/Tender · AuditLog **[V2]**. (Current schema in `fiscal-core/app/models.py`
covers Merchant/MerchantSecret/InvoiceChain/Document; POS/User/Product to be added.)

## 8. Constraints & assumptions
- Host = **Ethio Telecom Linux server, ~2 Mbps** → lightweight/server-rendered mandatory.
- Currency ETB; VAT 15%; domestic withholding 3%; Ethiopian + Gregorian calendars.
- Merchants are MoR-registered taxpayers with (or able to obtain) EIMS credentials + INSA cert.
- Receipt is an independent product, **not** a government service (disclaimer required, per
  landing/slip.et).

## 9. Release plan
- **MVP:** phone/OTP auth · onboarding + MoR connect · POS (cash/mobile-money, VAT) ·
  B2C+B2B invoice register · sales receipt · cancel · credit/debit memo · thermal+A4 print
  with QR · receipt history · dashboard · RBAC core · single branch.
- **V2:** offline PWA + sync · inventory · full reports (Z/VAT/withholding) · notifications ·
  branches/sub-TIN · withholding receipt · card payments · VAT-cert OCR.
- **LATER:** hardware bundles (handheld/duo/stand/printer, per slip.et) · aggregator
  self-serve merchant onboarding · marketplace/digital menu.

## 10. Traceability (MoR BSP Master → requirements)
IRC-P01→FR-D1 · IRC-P02→FR-D2 · IRC-P03→FR-D3 · IRC-P04→FR-D4 · IRC-P05→FR-D6 ·
IRC-P06/P07→FR-D5 · IRC-N08→FR-D2 · IRC-N09→FR-D3 · IRC-N010→FR-D6 · ADD-N001→FR-J ·
ADD-C001→FR-H/NFR-SEC · ADD-P001→FR-E · Section A→NFR-* · Section C→FR-K · Section H→§6.
