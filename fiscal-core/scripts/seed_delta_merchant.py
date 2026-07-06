"""Seed Delta SPMU as merchant #1 (idempotent).

Non-secret values are the sandbox-confirmed constants from
``docs/MOR_EIMS_CONTRACT.md`` §8. Secrets are NOT hard-coded — only *references*
are stored, resolved at call time by the secrets backend:

  * ``client_id``        : literal, read from env DELTA_EIMS_CLIENT_ID (an id, not a secret)
  * ``client_secret``    : ref "env:DELTA_EIMS_CLIENT_SECRET"
  * ``api_key``          : ref "env:DELTA_EIMS_API_KEY"
  * ``private_key_ref``  : env DELTA_EIMS_PRIVATE_KEY_PATH  (a file path)
  * ``certificate_ref``  : env DELTA_EIMS_CERT_PATH         (a file path)
  * ``base_url``         : env DELTA_EIMS_BASE_URL          (the sandbox host)
  * ``vat_number``       : env DELTA_EIMS_VAT_NUMBER        (sandbox seed 43256663343256663322)
  * default buyer        : NID / env DELTA_EIMS_DEFAULT_BUYER_ID (sandbox 3333367896666)

Run:  python -m scripts.seed_delta_merchant
"""

from __future__ import annotations

import os
import sys

# Ensure `app` is importable when run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import Base, SessionLocal, engine  # noqa: E402
from app import models  # noqa: E402,F401  (register tables on Base.metadata)
from app.models import Merchant, MerchantSecret  # noqa: E402

DELTA_TIN = "0107184904"

# Non-secret seed (MOR_EIMS_CONTRACT.md §8).
MERCHANT_FIELDS = dict(
    tin=DELTA_TIN,
    legal_name="DELTA AESTHETICS",
    system_type="POS",
    system_number="B3D3D9DC50",
    tax_code="VAT15",
    price_vat_inclusive=True,
    region="1",
    city="101",
    wereda="13",          # value from Delta's DEPLOYED working config (not the script template's 11)
    kebele=None,          # 7017: omit
    house_number=None,    # 7017: omit
    country=None,         # mirror the proven working payload exactly
    email=None,           # mirror the proven working payload exactly
    phone=None,           # 7017: mismatched vs MoR enterprise record — omit
    default_buyer_id_type="NID",
    tls_verify=False,          # sandbox often presents a self-signed / IP cert
    encrypt_payload=False,
    status="active",
)


def _secret_refs() -> dict:
    return dict(
        client_id=os.environ.get("DELTA_EIMS_CLIENT_ID"),
        client_secret="env:DELTA_EIMS_CLIENT_SECRET",
        api_key="env:DELTA_EIMS_API_KEY",
        private_key_ref=os.environ.get("DELTA_EIMS_PRIVATE_KEY_PATH"),
        certificate_ref=os.environ.get("DELTA_EIMS_CERT_PATH"),
    )


def main() -> int:
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        from sqlalchemy import select

        merchant = session.execute(
            select(Merchant).where(Merchant.tin == DELTA_TIN)
        ).scalar_one_or_none()

        fields = dict(MERCHANT_FIELDS)
        fields["base_url"] = os.environ.get("DELTA_EIMS_BASE_URL")
        fields["vat_number"] = os.environ.get("DELTA_EIMS_VAT_NUMBER")
        fields["default_buyer_id_number"] = os.environ.get("DELTA_EIMS_DEFAULT_BUYER_ID", "3333367896666")

        if merchant is None:
            merchant = Merchant(**fields)
            merchant.secret = MerchantSecret(**_secret_refs())
            session.add(merchant)
            action = "created"
        else:
            for k, v in fields.items():
                setattr(merchant, k, v)
            if merchant.secret is None:
                merchant.secret = MerchantSecret(**_secret_refs())
            else:
                for k, v in _secret_refs().items():
                    setattr(merchant.secret, k, v)
            action = "updated"

        session.commit()
        print(f"[seed] Delta merchant {action}: TIN {DELTA_TIN} (id={merchant.id})")

        # Report which secrets are actually resolvable right now.
        missing = []
        for env in ("DELTA_EIMS_CLIENT_ID", "DELTA_EIMS_CLIENT_SECRET", "DELTA_EIMS_API_KEY",
                    "DELTA_EIMS_BASE_URL", "DELTA_EIMS_VAT_NUMBER"):
            if not os.environ.get(env):
                missing.append(env)
        for env in ("DELTA_EIMS_PRIVATE_KEY_PATH", "DELTA_EIMS_CERT_PATH"):
            path = os.environ.get(env)
            if not path:
                missing.append(env)
            elif not os.path.isfile(path):
                missing.append(f"{env} (file not found: {path})")

        if missing:
            print("[seed] WARNING — these are not set yet (needed for sandbox calls):")
            for m in missing:
                print(f"          - {m}")
            print("[seed] Set them in fiscal-core/.env (see .env.example), then run the smoke test.")
        else:
            print("[seed] All Delta sandbox secrets are present. Ready for: python -m scripts.sandbox_smoke")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
