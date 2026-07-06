"""Generate an RSA-3072 private key + INSA-shaped CSR for an EIMS system.

Reusable for EVERY identity the platform needs: Receipt's own system, and each
merchant onboarded under the BSP model (each merchant gets its own INSA cert,
per the certification plan). Follows the MoR certificate guideline exactly:
RSA 3072, CN = taxpayer TIN, serialNumber = System Number (from MoR portal
Source Management), plus C/ST/L/O/OU/emailAddress.

Pure Python (cryptography) — no openssl.exe / shell-quoting issues on Windows.

Usage:
  python -m scripts.make_insa_csr --tin 0107184904 --system B3D3D9DC50 \
      --org "DELTA AESTHETICS" --email billing@deltaspmu.com --slug delta
  # -> secrets/<slug>/private_key.key        (chmod 600 — NEVER share/commit)
  # -> secrets/<slug>/<TIN>-<SYSTEM>.csr.pem (email to ica@insa.gov.et with the form)

Then submit per docs/INSA_CERT_REQUEST.md and install the issued chain as
secrets/<slug>/certificate.pem.
"""

from __future__ import annotations

import argparse
import os
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate INSA key + CSR for an EIMS system")
    ap.add_argument("--tin", required=True, help="Taxpayer TIN (becomes CN)")
    ap.add_argument("--system", required=True, help="MoR System Number (becomes serialNumber)")
    ap.add_argument("--org", required=True, help="Organization legal name (O / OU)")
    ap.add_argument("--email", required=True, help="Contact email (emailAddress)")
    ap.add_argument("--ou", default=None, help="Organizational unit (default: same as --org)")
    ap.add_argument("--slug", default=None, help="Output folder name under secrets/ (default: TIN)")
    ap.add_argument("--outdir", default=None, help="Override output directory entirely")
    args = ap.parse_args()

    slug = args.slug or args.tin
    outdir = args.outdir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "secrets", slug
    )
    os.makedirs(outdir, exist_ok=True)
    key_path = os.path.join(outdir, "private_key.key")
    csr_path = os.path.join(outdir, f"{args.tin}-{args.system}.csr.pem")

    if os.path.exists(key_path):
        print(f"[!] {key_path} already exists — refusing to overwrite a private key.")
        print("    Move it away first if you really want a new one.")
        return 2

    # RSA-3072 per the MoR certificate guideline (§3.1).
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    with open(key_path, "wb") as fh:
        fh.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass  # Windows ACLs; best-effort

    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "ET"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Addis Ababa"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Addis Ababa"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, args.org),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, args.ou or args.org),
        x509.NameAttribute(NameOID.COMMON_NAME, args.tin),          # CN = TIN
        x509.NameAttribute(NameOID.SERIAL_NUMBER, args.system),      # System Number
        x509.NameAttribute(NameOID.EMAIL_ADDRESS, args.email),
    ])
    csr = x509.CertificateSigningRequestBuilder().subject_name(subject).sign(key, hashes.SHA256())
    with open(csr_path, "wb") as fh:
        fh.write(csr.public_bytes(serialization.Encoding.PEM))

    print(f"[ok] private key : {key_path}   (KEEP SECRET — never email/commit)")
    print(f"[ok] CSR         : {csr_path}")
    print(f"     subject     : C=ET, O={args.org}, CN={args.tin}, serialNumber={args.system}")
    print()
    print("Next: attach the CSR + the filled Certificate Request Form to an email")
    print("      to ica@insa.gov.et  (see docs/INSA_CERT_REQUEST.md).")
    print("      Install the issued chain as the same folder's certificate.pem.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
