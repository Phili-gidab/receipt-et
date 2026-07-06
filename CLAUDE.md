# Receipt — project guide (read me first)

**Receipt** = API-first, multi-tenant **aggregator/BSP** for Ethiopia's MoR **EIMS**
e-invoicing. Signs + registers fiscal documents for many merchants. Python/FastAPI
fiscal core + Postgres + Terraform (AWS). (Folder/package were scaffolded under the
placeholder "receipt" then rebranded to "receipt".)

## Source of truth
[`docs/MOR_EIMS_CONTRACT.md`](docs/MOR_EIMS_CONTRACT.md) — the **sandbox-validated**
MoR request contract (reverse-engineered from Delta SPMU, proven 2026-06-12). Conform
to it exactly: envelope, canonical JSON, signing, field rules, and the
**DO-NOT-INHERIT** list (§7).

## Non-negotiable invariants
- **Keys are per-merchant and server-side only.** `crypto.py` is pure (takes key/cert
  as args). Never put a private key in a client app.
- **Exact-bytes signing:** the canonical request string is the wire body — never
  re-serialize. (`crypto.build_signed_body`.)
- **Per-merchant chain** (counter + last_irn), serialized by a Postgres advisory lock
  (`locks.py`), advanced **only on success**, idempotent on
  `(merchant, transaction_ref)` (`registration.py`).
- **Secrets are references**, resolved at call time via `secrets_backend.py`
  (env/files locally, AWS Secrets Manager in cloud) — never plaintext in the DB.

## Layout
- `app/crypto.py` `mor_client.py` `invoice_builder.py` `receipt_builder.py`
  `note_builder.py` `registration.py` `models.py` `schemas.py` `db.py` `config.py`
  `secrets_backend.py` `printing.py` `routers/*` `main.py`
- `scripts/seed_delta_merchant.py`, `scripts/sandbox_smoke.py`
- `infra/*.tf`

## Commands
```bash
cd fiscal-core
python -m scripts.seed_delta_merchant     # tables + Delta merchant (idempotent)
python -m scripts.sandbox_smoke           # auth -> invoice -> receipt (needs real creds)
python -m pytest -q                       # crypto + mor_client + builder tests
uvicorn app.main:app --reload             # /docs OpenAPI
cd ../infra && terraform plan -var-file=terraform.tfvars   # AWS (profile delta, eu-central-1) — DO NOT apply without review
```

## Tests already passing
crypto (9), mor_client (29), invoice_builder (24). The app layer
(routers/registration) needs `fastapi`+`sqlalchemy`+`pydantic` installed + a Postgres
to import-test; deps weren't installable offline during the build — run
`pip install -r requirements.txt` then `python -c "import app.main"`.

## Strategy
API-first wedge vs the merchant-POS incumbent (deresegn.et). We are the rails other
POS/ERP/SaaS vendors fiscalize through. See `docs/ARCHITECTURE.md`.
