# Receipt — Architecture

## Positioning
API-first **fiscalization-as-a-service**. The incumbent (deresegn.et) is a
merchant-facing receipt POS; Receipt is the **rails** other POS/ERP/SaaS vendors and
developers fiscalize through. The same fiscal core can also power our own thin POS
later, but the wedge is the API.

## Components

```
   Developers / POS / ERP / our own apps
                 │  HTTPS (API key, sandbox|live)        ← planned dev layer
                 ▼
        ┌────────────────────────────┐
        │  Fiscal Core (FastAPI)     │
        │  routers → registration    │   per-merchant, idempotent, locked chain
        │  → builders → mor_client   │   sign (SHA512withRSA) + POST envelope
        └─────┬───────────────┬──────┘
              │               │
   Postgres (tenants,    Secrets backend (KMS / Secrets Manager / env)
   chains, documents)    per-merchant private key + cert + credentials
              │
              ▼
     MoR EIMS  (/auth/login, /v1/register, /v1/cancel, /v1/verify, /v1/receipt/sales)
```

## Multi-tenancy (the core difference vs Delta)
Everything that was global config in Delta is **per-merchant** here:
`Merchant` (TIN, system type/number, seller details, tax code, base URL, toggles),
`MerchantSecret` (credential *references*), `InvoiceChain` (counter + last_irn),
`Document` (idempotent on `(merchant, transaction_ref)`). Each merchant's chain is
serialized by a Postgres advisory lock keyed on TIN.

## Request flow (register)
1. Router builds a service `tx` from the API request, loads the merchant.
2. `registration.register_invoice_for_merchant` takes the per-merchant advisory lock,
   checks idempotency, reads the chain head, builds the invoice
   (`previous_irn = last_irn`, `counter+1`).
3. `mor_client` builds the `{request,signature,certificate}` envelope (exact-bytes,
   signed with the merchant's key) and POSTs it; one 401 re-login retry.
4. On `statusCode==200`: persist `irn/qr/signedInvoice`, advance the chain, commit.
   Else mark the document `Failed` (chain untouched, retryable).

## Security
- **Private keys never leave the server.** `crypto.py` is pure and per-merchant;
  signing happens only in the fiscal core. Client apps call the API, never sign.
- Secrets resolved at call time from KMS/Secrets Manager (cloud) or env/files (dev);
  the DB stores only references.
- TLS to MoR (`tls_verify` per merchant — off only for the sandbox self-signed cert).

## Hosting & portability
- **Now:** AWS, profile `delta`, eu-central-1 (Frankfurt). Containerized (Docker) so
  it's portable.
- **Later (MoR/INSA data residency):** migrate to **in-Ethiopia** hosting (Ethio
  Telecom VPS/Cloud/Bare Metal). Because the app is a container + Postgres, the move is
  re-point infra, not a rewrite. Keep `infra/` modular.

## Planned (developer layer for the API-first wedge)
API keys per developer + sandbox/live modes, webhooks (invoice registered/failed),
SDKs (JS/Python/PHP), a thin dashboard, rate limiting. FastAPI already emits OpenAPI
at `/docs` for the SDK generation.

## Offline (for any POS built on top)
Cloud pattern: client issues a provisional receipt offline → registers + gets IRN/QR
on reconnect; idempotency keys + the per-merchant lock keep the chain ordered. True
on-device signing is only for hardware S-POS (out of scope for v1).
