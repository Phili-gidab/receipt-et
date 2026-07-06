# Receipt — API-first fiscalization for Ethiopia (MoR EIMS)

**Receipt** is an **API-first, multi-tenant aggregator** for Ethiopia's Ministry of
Revenue **EIMS** e-invoicing — the "Stripe for MoR e-invoicing." It signs and
registers invoices, sales receipts, and credit/debit notes with MoR on behalf of
many merchants, each with its own TIN, certificate, credentials, and invoice chain.

> Reuses the **sandbox-validated** MoR request contract proven in the Delta SPMU
> project (`core.mor.gov.et`, 2026-06-12). The exact contract lives in
> [`docs/MOR_EIMS_CONTRACT.md`](docs/MOR_EIMS_CONTRACT.md) — the source of truth.

## What's here

```
Receipt/
├── fiscal-core/            # FastAPI service (the product)
│   ├── app/
│   │   ├── crypto.py         # canonical JSON + SHA512withRSA signing (pure, per-merchant)
│   │   ├── mor_client.py     # transport/auth: login, signed_post, register/cancel/verify/receipt
│   │   ├── invoice_builder.py / receipt_builder.py / note_builder.py   # exact MoR payloads
│   │   ├── registration.py   # locked, idempotent, per-merchant chain orchestration
│   │   ├── models.py / schemas.py / db.py / config.py / secrets_backend.py
│   │   ├── printing.py       # A4 + thermal HTML with embedded QR
│   │   ├── routers/          # merchants, invoices (register/cancel/verify/receipt/notes), admin
│   │   └── main.py           # FastAPI app (+ OpenAPI at /docs)
│   ├── scripts/
│   │   ├── seed_delta_merchant.py   # Delta = merchant #1 (idempotent)
│   │   └── sandbox_smoke.py         # end-to-end sandbox proof (invoice + receipt)
│   └── tests/                # crypto (9), mor_client (29), builders (24) — all pass
├── infra/                  # Terraform (AWS, profile `delta`, eu-central-1) — validated
└── docs/                   # contract, architecture, runbook, certification plan
```

## Quick start (local)

```bash
cd fiscal-core
cp .env.example .env                 # fill DELTA_EIMS_* + cert/key paths
docker compose up -d db              # or run your own Postgres
python -m venv .venv && . .venv/Scripts/activate   # (Windows) or source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.seed_delta_merchant   # creates tables + seeds Delta
python -m scripts.sandbox_smoke         # auth -> register invoice -> register receipt
uvicorn app.main:app --reload           # API + Swagger at http://localhost:8000/docs
```

## The wedge

The incumbent (deresegn.et) is a merchant-facing receipt POS. **Receipt** instead
sells *rails*: a clean REST API + (planned) SDKs + webhooks so other POS/ERP/SaaS
vendors fiscalize through us. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Status

Foundation + transport + builders + registration service + API + Terraform are built
and (where deps allow) tested. **Sandbox registration is gated only on dropping
Delta's real credentials into `.env`** (see [`docs/RUNBOOK.md`](docs/RUNBOOK.md)).
Certification path: [`docs/CERTIFICATION_PLAN.md`](docs/CERTIFICATION_PLAN.md).
