# Receipt — Runbook

## A. Get the sandbox working with Delta (merchant #1)

### 1. Fetch Delta's sandbox credentials off the EC2 box
Delta's secrets are NOT in any repo. On the Delta server:

```bash
# Credentials (from site_config.json)
sudo grep -E 'eims_(client_id|client_secret|api_key|tin|seller_vat|base_url)' \
  /home/frappe/deltaspmu/sites/api.deltaspmu.com/site_config.json
# or: cat .../site_config.json | python -m json.tool | grep eims_

# Certificate + private key
ls -l /home/frappe/deltaspmu/eims/
sudo cat /home/frappe/deltaspmu/eims/certificate.pem
sudo cat /home/frappe/deltaspmu/eims/private_key.key
```

### 2. Drop them into fiscal-core
```bash
cd fiscal-core
cp .env.example .env
mkdir -p secrets/delta
# paste the two files:
#   secrets/delta/private_key.key   (chmod 600)
#   secrets/delta/certificate.pem
chmod 600 secrets/delta/private_key.key
# edit .env: DELTA_EIMS_BASE_URL / CLIENT_ID / CLIENT_SECRET / API_KEY / VAT_NUMBER
#            DELTA_EIMS_PRIVATE_KEY_PATH=./secrets/delta/private_key.key
#            DELTA_EIMS_CERT_PATH=./secrets/delta/certificate.pem
```
> `secrets/` and `.env` are gitignored. Never commit them.

### 3. Run it
```bash
docker compose up -d db                 # or your own Postgres at DATABASE_URL
pip install -r requirements.txt
python -m scripts.seed_delta_merchant   # creates tables + seeds Delta; reports missing vars
python -m scripts.sandbox_smoke         # login -> register invoice -> register receipt
```
Expected: `login OK`, an **IRN** + a present **QR**, then a **RRN** for the receipt.
If the receipt 400/406s, tweak `app/receipt_builder.py` field names per MoR's response
(that path is coded-but-unvalidated) and re-run.

### 4. Auth-casing fallback
If `login FAILED` with a 4xx, flip the auth key casing: in `app/mor_client.py` pass
`key_map=AUTH_KEY_MAP_LOWERCASE` (or set it as the default) and retry — see
DO-NOT-INHERIT #2 in the contract.

## B. Onboard another merchant (the aggregator flow)
```bash
curl -X POST http://localhost:8000/merchants -H 'content-type: application/json' -d '{
  "tin":"NEWTIN", "legal_name":"ACME PLC", "system_type":"POS",
  "system_number":"XXXX", "base_url":"https://core.mor.gov.et", "tax_code":"VAT15",
  "vat_number":"...", "region":"1","city":"101","wereda":"11",
  "default_buyer_id_type":"NID","default_buyer_id_number":"...",
  "tls_verify":false,
  "secret":{ "client_id":"...", "client_secret":"env:ACME_CLIENT_SECRET",
             "api_key":"env:ACME_API_KEY",
             "private_key_ref":"./secrets/acme/private_key.key",
             "certificate_ref":"./secrets/acme/certificate.pem" }
}'
# then:
curl -X POST http://localhost:8000/admin/NEWTIN/test-login
curl -X POST http://localhost:8000/merchants/NEWTIN/invoices -d '{...RegisterInvoiceRequest...}'
```
Each merchant gets its own INSA certificate + MoR source-system credentials (see the
certification plan). Production: store secrets in AWS Secrets Manager
(`SECRETS_BACKEND=aws`), refs become secret ids.

## C. API surface
`/docs` (Swagger). Key routes:
`POST /merchants`, `GET /merchants`, `GET /merchants/{tin}`,
`POST /merchants/{tin}/invoices`, `POST /merchants/{tin}/invoices/{irn}/cancel`,
`GET /merchants/{tin}/invoices/{irn}/verify`, `POST /merchants/{tin}/receipts`,
`POST /merchants/{tin}/credit-notes`, `POST /merchants/{tin}/debit-notes`,
`GET/POST /admin/{tin}/{config-status,test-login,reconciliation,retry}`.

## D. Deploy (AWS, gated)
```bash
cd infra
terraform init
terraform plan  -var-file=terraform.tfvars     # REVIEW the plan + cost first
terraform apply -var-file=terraform.tfvars      # only after sign-off
```
Uses AWS profile `delta`, eu-central-1. See `infra/README.md`.
