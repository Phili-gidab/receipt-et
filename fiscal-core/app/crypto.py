"""Pure crypto + envelope builders for the MoR EIMS transport.

Ported VERBATIM from MOR_EIMS_CONTRACT.md §0 and the sandbox-validated Delta
implementation (Delta_SPMU/backend/frappe-lms/lms/lms/eims.py lines 228-311).

Every function here is PURE: it takes the merchant's private key object / cert
PEM as ARGUMENTS and reads no global/per-process fiscal config. This is what
makes the service multi-tenant safe.

Transport invariants reproduced byte-for-byte (spec §0):
  * Envelope: {"request": <obj>, "signature": <b64>, "certificate": <b64>}.
  * signature = base64( SHA512withRSA / RSASSA-PKCS1-v1_5 over the CANONICAL
    JSON string of <obj> ), using the merchant's private key.
  * Exact-bytes rule: the canonical string that was signed is the EXACT bytes
    placed on the wire. The envelope is built by string interpolation, never by
    re-serializing <obj> through a JSON library a second time.
  * Canonical JSON: json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    — compact, no whitespace, key order preserved (NOT sorted), UTF-8, raw
    Unicode.
"""

import base64
import hashlib
import json
import os

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives import padding as sym_padding
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

__all__ = [
    "canonical",
    "sign",
    "certificate_b64",
    "build_signed_body",
    "load_private_key_from_pem",
    "derive_encryption_key",
    "encrypt_payload",
]


def canonical(obj) -> str:
    """Deterministic compact JSON (no whitespace), preserving key order.

    Matches the "Parsed String to be signed" form in certificate_guideline.pdf.
    We sign this exact string AND send these exact bytes on the wire so the
    server verifies against an identical serialisation.
    """
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def load_private_key_from_pem(pem: str) -> RSAPrivateKey:
    """Load a PKCS#8 RSA private key from PEM text (password=None).

    If the input has no ``-----BEGIN`` header it is treated as a bare base64
    body and wrapped as a PKCS#8 PEM (``openssl genpkey -algorithm RSA`` emits
    "BEGIN PRIVATE KEY"). Pure: the PEM is passed in, never read from config.
    """
    if "-----BEGIN" not in pem:
        pem = "-----BEGIN PRIVATE KEY-----\n" + pem.strip() + "\n-----END PRIVATE KEY-----"
    return serialization.load_pem_private_key(
        pem.encode(), password=None, backend=default_backend()
    )


def sign(canonical_string: str, private_key) -> str:
    """SHA512withRSA (RSASSA-PKCS1-v1_5) over the canonical string -> base64.

    ``private_key`` is a loaded cryptography private key object (the merchant's).
    """
    sig = private_key.sign(
        canonical_string.encode("utf-8"), padding.PKCS1v15(), hashes.SHA512()
    )
    return base64.b64encode(sig).decode()


def certificate_b64(cert_pem: str) -> str:
    """Return the base64-encoded INSA certificate chain for the request body.

    If the input already looks base64 (no PEM/Subject markers) it is returned
    stripped, unchanged.
    """
    if "-----BEGIN CERTIFICATE-----" in cert_pem or "Subject:" in cert_pem:
        return base64.b64encode(cert_pem.encode("utf-8")).decode()
    return cert_pem.strip()  # already base64


def build_signed_body(request_obj, private_key, cert_pem: str) -> bytes:
    """Construct the exact ``{request, signature, certificate}`` JSON bytes.

    Built as a string (not via a JSON library re-serializing ``request_obj``)
    so the request bytes on the wire are byte-for-byte what we signed. The
    ``signature`` and ``certificate`` strings ARE JSON-encoded (to quote/escape
    them safely), but the canonical ``request`` substring is interpolated raw.
    """
    c = canonical(request_obj)
    body = '{"request":%s,"signature":%s,"certificate":%s}' % (
        c,
        json.dumps(sign(c, private_key)),
        json.dumps(certificate_b64(cert_pem)),
    )
    return body.encode("utf-8")


# ---------------------------------------------------------------------------
# Optional payload encryption — KEEP OFF (spec §0).
# ---------------------------------------------------------------------------
# Best-guess AES-256-CBC keyed by sha256(encryptionKey), random 16-byte IV
# prepended, whole thing base64-encoded and wrapped as {"data": <b64>}. The
# spec blanks the real algorithm and sandbox 2026-06-12 confirmed /v1/register
# needs NO encryption. Implemented for completeness; default OFF — do not block
# on it. Confirm the real algorithm/format with MoR before enabling.


def derive_encryption_key(encryption_key: str) -> bytes:
    """Derive the AES-256 key as sha256(encryptionKey)."""
    return hashlib.sha256((encryption_key or "").encode("utf-8")).digest()


def encrypt_payload(plaintext_bytes: bytes, encryption_key: str) -> str:
    """AES-256-CBC encrypt; return base64(IV || ciphertext).

    PKCS7 padding (128-bit block), random 16-byte IV prepended. The caller is
    responsible for wrapping the result as ``{"data": <return value>}`` if/when
    encryption is ever enabled.
    """
    key = derive_encryption_key(encryption_key)
    iv = os.urandom(16)
    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(plaintext_bytes) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    enc = cipher.encryptor()
    ct = enc.update(padded) + enc.finalize()
    return base64.b64encode(iv + ct).decode()
