# Getting an EIMS identity (System ID + INSA certificate) — Receipt & every merchant

Two identities matter, and the process is identical for both:

| Identity | TIN used | When |
|---|---|---|
| **Receipt itself** (our BSP system) | Receipt's company TIN (needs business registration first) | Start now — longest pole |
| **Each merchant** we onboard (e.g. Delta) | The merchant's TIN | At onboarding |

## Step 0 — Prerequisites
- A **TIN** (for Receipt: register the company → trade license + TIN. Delta's for reference:
  TIN `0107184904`, reg `AACATB/14/673/50366961/2018`, legal name "DELTA AESTHETICS TRANING PLC").
- Contact person name / phone / email.

## Step 1 — MoR portal self-onboarding (gets portal login)
Per the MoR *Self-Onboarding and Source Registration Guide*:
1. Portal signup page → enter **TIN**, pick a notification option (email/SMS), accept T&C → Register.
2. Enter the verification code (check spam).
3. Portal emails **login credentials** → log in → **enable 2FA**.

## Step 2 — Source registration (gets the SYSTEM NUMBER)
1. Portal → **Source Management** → *Enterprise* → pick the **establishment**.
2. **Add source** → select source system number from the dropdown → search → submit.
3. Status = *pending* → approved by an MoR officer in back office.
4. Result: an approved **System Number** (e.g. Delta's `B3D3D9DC50`) + the API
   **Client ID / Client Secret / API key** for that source.

## Step 3 — Key + CSR (our tool)
```bash
cd fiscal-core
python -m scripts.make_insa_csr --tin <TIN> --system <SYSTEM_NUMBER> \
    --org "<LEGAL NAME>" --email <contact@email> --slug <folder-name>
# -> secrets/<slug>/private_key.key          (NEVER leaves this machine)
# -> secrets/<slug>/<TIN>-<SYSTEM>.csr.pem   (safe to email)
```
RSA-3072, CN=TIN, serialNumber=SystemNumber — exactly the guideline's shape.

## Step 4 — Submit to INSA
Email to **ica@insa.gov.et**, attaching (1) the CSR and (2) the filled
**E-Invoice Digital Certificate Request Form** (contact person, org name + TIN,
and the System ID table). Template:

> **Subject:** Certificate Request for E-Invoice
>
> Dear Admin,
> This is a certificate request for E-Invoice.
> Please find attached: 1. Request Form  2. CSR File
> Regards, <name> — <organization> — <phone / email>

Turnaround observed on the Delta request: **~1 day** (CSR Jun 18 → cert Jun 19).
Certs are short-lived (Delta's: Jun 19 → **Sep 17, 2026**, ~90 days) — diarize renewal.

## Step 5 — Install
Save the returned chain (3 PEM certificates) as `secrets/<slug>/certificate.pem`,
alongside its `private_key.key`. Wire the merchant row's `certificate_ref` /
`private_key_ref` (or the `DELTA_EIMS_*` env for Delta). Verify the pair matches:
```bash
openssl x509 -in certificate.pem -noout -pubkey | openssl md5   # must equal:
openssl pkey -in private_key.key -pubout      | openssl md5
```
Then `python -m scripts.sandbox_smoke`.

## Receipt-specific sequence (the critical path)
1. **Company registration** → Receipt legal name + TIN  ← longest lead time, start first
2. Portal self-onboard with Receipt's TIN (Step 1)
3. Register Receipt's source system → System Number + API creds (Step 2)
4. `make_insa_csr --tin <receipt-tin> --system <receipt-sys> --slug receipt` (Step 3)
5. Email INSA (Step 4) → install (Step 5) → Receipt signs as ITSELF in sandbox
6. Proceed to the BSP certification checklist (docs/CERTIFICATION_PLAN.md)

## Sandbox error decoder (learned the hard way)
- `67011 "Certificate Or Signature Validation Error"` — cert not INSA-issued /
  wrong pair / bad signature bytes. The gateway checks this BEFORE credentials.
- Login rejects → try lowercase auth keys (`clientid`/`clientsecret`) — casing
  is configurable in `mor_client` (`AUTH_KEY_MAP_LOWERCASE`).
