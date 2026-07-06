"""GOLDEN tests for app.crypto — prove byte-exact transport semantics (spec §0).

These tests import ONLY app.crypto (which depends only on ``cryptography`` +
stdlib), so they run without a database, FastAPI, or any service config.

Covered:
  (a) canonical() preserves key order and emits no whitespace.
  (b) sign() is a correct SHA512withRSA / PKCS1v15 signature — generated with an
      ephemeral RSA-3072 key and verified against the public key.
  (c) build_signed_body()'s embedded ``request`` substring is byte-identical to
      canonical(obj) (the exact-bytes rule).
"""

import base64
import json

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.crypto import (
    build_signed_body,
    canonical,
    certificate_b64,
    load_private_key_from_pem,
    sign,
)


@pytest.fixture(scope="module")
def rsa3072():
    """An ephemeral RSA-3072 key pair for signing tests."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    return key, key.public_key()


# (a) canonical: key order preserved, no whitespace.
def test_canonical_preserves_key_order_and_strips_whitespace():
    assert canonical({"b": 1, "a": "x"}) == '{"b":1,"a":"x"}'


def test_canonical_no_whitespace_nested_and_unicode():
    obj = {"z": [1, 2, {"q": "ሰላም"}], "a": None}
    out = canonical(obj)
    # No spaces after separators; key order preserved (z before a, q kept).
    assert out == '{"z":[1,2,{"q":"ሰላም"}],"a":null}'
    assert " " not in out  # raw unicode, compact separators -> no ascii spaces


def test_canonical_null_not_empty_string():
    # First-invoice PreviousIrn must serialize to JSON null, never "" (spec §7.1).
    assert canonical({"PreviousIrn": None}) == '{"PreviousIrn":null}'


# (b) sign: correct SHA512withRSA / PKCS1v15 signature, verified with public key.
def test_sign_produces_verifiable_pkcs1v15_sha512_signature(rsa3072):
    priv, pub = rsa3072
    message = '{"hello":"world","n":42}'

    sig_b64 = sign(message, priv)
    sig = base64.b64decode(sig_b64)

    # Verify with the public key — raises InvalidSignature if wrong.
    pub.verify(sig, message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA512())


def test_sign_rejects_tampered_message(rsa3072):
    priv, pub = rsa3072
    sig = base64.b64decode(sign('{"a":1}', priv))
    with pytest.raises(InvalidSignature):
        pub.verify(sig, b'{"a":2}', padding.PKCS1v15(), hashes.SHA512())


# (c) build_signed_body: embedded request substring == canonical(obj) bytes.
def test_build_signed_body_request_substring_is_byte_identical(rsa3072):
    priv, _pub = rsa3072
    obj = {"TransactionType": "B2C", "Version": "1", "PreviousIrn": None}
    cert_pem = "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----"

    body = build_signed_body(obj, priv, cert_pem)
    assert isinstance(body, bytes)

    c = canonical(obj)
    expected_prefix = b'{"request":' + c.encode("utf-8") + b","
    assert body.startswith(expected_prefix)

    # The whole envelope must still be valid JSON, and request must round-trip
    # back to the original object with identical key order.
    parsed = json.loads(body.decode("utf-8"))
    assert canonical(parsed["request"]) == c
    assert list(parsed["request"].keys()) == list(obj.keys())

    # signature in the envelope verifies against the canonical request bytes.
    sig = base64.b64decode(parsed["signature"])
    _pub.verify(sig, c.encode("utf-8"), padding.PKCS1v15(), hashes.SHA512())


def test_build_signed_body_signature_matches_request_not_reserialized(rsa3072):
    """Guard the exact-bytes rule: signature covers the wire request bytes."""
    priv, pub = rsa3072
    # Key order chosen so a sorted re-serialization would differ.
    obj = {"b": 1, "a": 2}
    body = build_signed_body(obj, priv, "already-base64-cert")
    parsed = json.loads(body)
    # request kept as {"b":1,"a":2}, not sorted to {"a":2,"b":1}.
    assert b'"request":{"b":1,"a":2}' in body
    sig = base64.b64decode(parsed["signature"])
    pub.verify(sig, b'{"b":1,"a":2}', padding.PKCS1v15(), hashes.SHA512())


# Round-trip: load_private_key_from_pem handles both wrapped and bare PEM.
def test_load_private_key_from_pem_roundtrip_and_bare_body():
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    # Full PEM loads.
    loaded = load_private_key_from_pem(pem)
    assert loaded.key_size == 3072

    # Bare base64 body (no BEGIN header) is wrapped and loads identically.
    body = "".join(
        line for line in pem.splitlines() if "-----" not in line
    )
    loaded2 = load_private_key_from_pem(body)
    assert loaded2.key_size == 3072


def test_certificate_b64_encodes_pem_but_passes_through_base64():
    pem = "-----BEGIN CERTIFICATE-----\nQUJD\n-----END CERTIFICATE-----"
    enc = certificate_b64(pem)
    assert base64.b64decode(enc).decode("utf-8") == pem

    already_b64 = "QUJDREVG"
    assert certificate_b64(already_b64) == already_b64
