# Receipt — MoR BSP Certification Plan (Aggregator / Section C)

Receipt is a **system provider / aggregator**, so the MoR `MoR_BSP_Master` checklist
applies as **Section C (Aggregator / Multi-Merchant Platform)** plus the core IRC/ADD
functional cases — not just Section A (single SaaS taxpayer, which is how Delta was
scoped). Reuse Delta's case-by-case mapping as the skeleton:
`C:/Users/ASUS/Desktop/Delta_SPMU/docs/EIMS_CERTIFICATION_GAP_ANALYSIS.md`.

## Functional cases (must pass in sandbox, ≥3 runs each, evidence = IRNs/RRNs + QR scans)
| Case | What | Status in Receipt |
|---|---|---|
| IRC-P01 | Register B2C invoice + print + QR | ✅ **PROVEN 2026-07-06** — IRN test-b38b…1b55, doc #39, signed QR (need 2 more runs for the ≥3 rule) |
| IRC-P02 | Register B2B invoice (buyer TIN+name) | done (buyer.tin → B2B); needs run |
| IRC-P03 | Sales receipt → RRN | ✅ **PROVEN 2026-07-06** — RRN test-f19e…2089 (need 2 more runs) |
| IRC-P05 | Cancel invoice (+ reject already-cancelled) | done (reason 1-4, persists cancelationDate, guard) |
| IRC-P06/P07 | Credit / Debit memo | done (Reason set, RelatedDocument=IRN, credit≤original) |
| IRC-N08 | Reject invalid buyer TIN | partial — add 10-digit + non-empty-name check |
| IRC-N09 | Reject receipt for non-existent/cancelled invoice | done (guards) |
| IRC-N010 | Reject cancel of non-existent/cancelled | done (guards) |
| ADD-N001 | Notifications (email/SMS) | **needs building** (no notifier yet) |
| ADD-C001 | Secrets not hard-coded; RBAC | done (refs/KMS); add admin RBAC for prod |
| ADD-P001 | Printing layout (normal + thermal) | done (`printing.py` A4 + thermal + QR) |

## Section C (Aggregator) specifics — the new surface vs Delta
- **Merchant data isolation** — per-merchant rows + (prod) per-merchant encryption keys;
  prove no cross-merchant leakage.
- **Per-merchant TIN/branch traceability** — every document ties to its merchant TIN
  (and sub-TIN/branch when modeled).
- **Per-merchant rate-limit handling** — one merchant can't starve others.
- **Merchant-specific dashboards/alerts**, exit/data-export per merchant.
- **Each merchant** has its own INSA certificate + MoR source-system credentials.

## Non-functional (Section A categories still apply)
Performance (<2s/call), reliability (daily backups + restore drill, auto-retry — built
`retry_failed`), monitoring/alerts + healthz (`/healthz` done; add CloudWatch/SNS),
TLS evidence, RBAC (add read-only viewer), audit logs ≥90d, DR diagram.

## External / legal path to become a certified provider
1. **Company** — Ethiopian business registration (TIN + trade license) under the
   "Receipt" legal name.
2. **System type** — register as **Aggregator** (Section C).
3. **INSA certificate** — generate RSA key + CSR per the cert guideline, email
   `ica@insa.gov.et` (our test system first; then one per onboarded merchant).
4. **MoR source-system approval** → Client ID / Secret / API key + System Number +
   confirmed sandbox base URL.
5. **Pass the checklist in sandbox** (above) — collect IRNs/RRNs/printouts/QR scans.
6. **INSA security audit** (OWASP/VA + pen test) — template from Delta's `INSA_*` docs.
7. **Commitment Form** (the Amharic undertaking) — 2-working-day onboarding SLA.
8. **Bank guarantee — USD 30,000** (Bank of Abyssinia template), 2-yr renewable.
9. **Certification review** → go live; onboard taxpayers within the SLA.

## Immediate gates
- Drop Delta's sandbox creds in and get one clean **IRC-P01** + the **receipt (P03)**
  round-trip (`scripts/sandbox_smoke.py`).
- Then close: notifications (ADD-N001), buyer-TIN validation (IRC-N08), per-merchant
  isolation hardening, and the Section C dashboard/rate-limit items.
