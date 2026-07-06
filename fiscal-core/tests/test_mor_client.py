"""Tests for app.mor_client — transport + auth layer (spec §0-§3).

These mock ``requests.post`` so they run with no network / DB. They prove:
  * _post_raw sends raw bytes (data=), correct headers, parses JSON / non-JSON.
  * login builds {clientId,clientSecret,apikey,tin} (casing configurable),
    reads data.accessToken/expiresIn/encryptionKey, caches per-merchant.
  * get_token caches and honours force=.
  * signed_post attaches Bearer, re-logs-in once on 401 and retries.
  * thin calls hit the right paths with the right key casing (Irn vs irn).
  * cancel validates ReasonCode in {1,2,3,4}.
"""

import json
import types

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import mor_client
from app.crypto import build_signed_body


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def priv_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def merchant():
    return types.SimpleNamespace(
        id=1, tin="0107184904", base_url="https://core.mor.gov.et/", tls_verify=False
    )


@pytest.fixture
def secrets(priv_key):
    return {
        "client_id": "cid",
        "client_secret": "csecret",
        "api_key": "akey",
        "private_key": priv_key,
        "certificate": "already-base64-cert",
    }


@pytest.fixture(autouse=True)
def _clear_cache():
    mor_client.clear_token_cache()
    yield
    mor_client.clear_token_cache()


class FakeResp:
    def __init__(self, status_code, payload, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is _NON_JSON:
            raise ValueError("no json")
        return self._payload


_NON_JSON = object()


@pytest.fixture
def captured(monkeypatch):
    """Patch requests.post; return a list of captured call kwargs + a queue."""
    calls = []
    responses = []

    def fake_post(url, data=None, headers=None, timeout=None, verify=None):
        calls.append(
            {"url": url, "data": data, "headers": headers, "timeout": timeout, "verify": verify}
        )
        return responses.pop(0)

    monkeypatch.setattr(mor_client.requests, "post", fake_post)
    return types.SimpleNamespace(calls=calls, responses=responses)


# --------------------------------------------------------------------------- #
# _post_raw
# --------------------------------------------------------------------------- #
def test_post_raw_sends_raw_bytes_and_headers(captured):
    captured.responses.append(FakeResp(200, {"ok": True}))
    status, parsed = mor_client._post_raw(
        "https://h", "/v1/register", b'{"a":1}', token="tok", tls_verify=False
    )
    assert status == 200 and parsed == {"ok": True}
    call = captured.calls[0]
    assert call["url"] == "https://h/v1/register"
    assert call["data"] == b'{"a":1}'  # raw bytes, not json=
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert call["timeout"] == 60
    assert call["verify"] is False


def test_post_raw_no_token_omits_auth_header(captured):
    captured.responses.append(FakeResp(200, {"ok": True}))
    mor_client._post_raw("https://h", "/auth/login", b"{}", token=None, tls_verify=True)
    assert "Authorization" not in captured.calls[0]["headers"]


def test_post_raw_non_json_returns_synthetic(captured):
    captured.responses.append(FakeResp(406, _NON_JSON, text="<html>err</html>"))
    status, parsed = mor_client._post_raw("https://h", "/x", b"{}", None, True)
    assert status == 406
    assert parsed["message"] == "NON_JSON_RESPONSE"
    assert "html" in parsed["body"]


# --------------------------------------------------------------------------- #
# login / get_token
# --------------------------------------------------------------------------- #
def _login_body_request(captured_call):
    """Extract the canonical request object from a captured login body."""
    return json.loads(captured_call["data"].decode("utf-8"))["request"]


def test_login_builds_camelcase_body_and_caches(merchant, secrets, captured):
    captured.responses.append(
        FakeResp(200, {"data": {"accessToken": "T1", "expiresIn": 600, "encryptionKey": "EK"}})
    )
    token = mor_client.login(merchant, secrets)
    assert token == "T1"

    req = _login_body_request(captured.calls[0])
    # Sandbox-proven camelCase + logical order preserved.
    assert list(req.keys()) == ["clientId", "clientSecret", "apikey", "tin"]
    assert req["clientId"] == "cid"
    assert req["tin"] == "0107184904"
    assert captured.calls[0]["url"].endswith("/auth/login")
    assert "Authorization" not in captured.calls[0]["headers"]  # login unauthed

    # Cached: a subsequent get_token does not hit the network.
    assert mor_client.get_token(merchant, secrets) == "T1"
    assert len(captured.calls) == 1


def test_login_lowercase_casing_map(merchant, secrets, captured):
    captured.responses.append(FakeResp(200, {"data": {"accessToken": "T"}}))
    mor_client.login(merchant, secrets, key_map=mor_client.AUTH_KEY_MAP_LOWERCASE)
    req = _login_body_request(captured.calls[0])
    assert list(req.keys()) == ["clientid", "clientsecret", "apikey", "tin"]


def test_login_no_token_raises(merchant, secrets, captured):
    captured.responses.append(FakeResp(401, {"message": "bad creds"}))
    with pytest.raises(mor_client.MorAuthError):
        mor_client.login(merchant, secrets)


def test_get_token_force_relogs(merchant, secrets, captured):
    captured.responses.append(FakeResp(200, {"data": {"accessToken": "A", "expiresIn": 600}}))
    captured.responses.append(FakeResp(200, {"data": {"accessToken": "B", "expiresIn": 600}}))
    assert mor_client.get_token(merchant, secrets) == "A"
    assert mor_client.get_token(merchant, secrets, force=True) == "B"
    assert len(captured.calls) == 2


def test_login_ttl_fallback_when_no_expiresin(merchant, secrets, captured, monkeypatch):
    captured.responses.append(FakeResp(200, {"data": {"accessToken": "T"}}))
    mor_client.login(merchant, secrets)
    # Token cached -> reused (proves a positive ttl was set from the fallback).
    captured.responses.append(FakeResp(200, {"data": {"accessToken": "OTHER"}}))
    assert mor_client.get_token(merchant, secrets) == "T"


# --------------------------------------------------------------------------- #
# signed_post — bearer + 401 retry
# --------------------------------------------------------------------------- #
def test_signed_post_attaches_bearer(merchant, secrets, captured):
    captured.responses.append(FakeResp(200, {"data": {"accessToken": "T", "expiresIn": 600}}))
    captured.responses.append(FakeResp(200, {"statusCode": 200, "body": {"irn": "IRN1"}}))
    parsed = mor_client.signed_post(merchant, secrets, "/v1/register", {"x": 1})
    assert parsed["body"]["irn"] == "IRN1"
    # Second call (the register) carried the bearer token.
    assert captured.calls[1]["headers"]["Authorization"] == "Bearer T"
    # And the body is the exact signed envelope (byte-exact request).
    assert b'"request":{"x":1}' in captured.calls[1]["data"]


def test_signed_post_relogs_once_on_401(merchant, secrets, captured):
    # login -> register(401) -> relogin -> register(200)
    captured.responses.append(FakeResp(200, {"data": {"accessToken": "T1", "expiresIn": 600}}))
    captured.responses.append(FakeResp(401, {"message": "expired"}))
    captured.responses.append(FakeResp(200, {"data": {"accessToken": "T2", "expiresIn": 600}}))
    captured.responses.append(FakeResp(200, {"statusCode": 200, "body": {"irn": "OK"}}))

    parsed = mor_client.signed_post(merchant, secrets, "/v1/register", {"x": 1})
    assert parsed["body"]["irn"] == "OK"
    assert len(captured.calls) == 4
    # Retried register used the fresh token.
    assert captured.calls[3]["headers"]["Authorization"] == "Bearer T2"


def test_signed_post_does_not_retry_twice_on_persistent_401(merchant, secrets, captured):
    captured.responses.append(FakeResp(200, {"data": {"accessToken": "T1", "expiresIn": 600}}))
    captured.responses.append(FakeResp(401, {"message": "expired"}))
    captured.responses.append(FakeResp(200, {"data": {"accessToken": "T2", "expiresIn": 600}}))
    captured.responses.append(FakeResp(401, {"message": "still expired"}))

    parsed = mor_client.signed_post(merchant, secrets, "/v1/register", {"x": 1})
    assert parsed["message"] == "still expired"
    assert len(captured.calls) == 4  # login, 401, relogin, 401 — no third register


# --------------------------------------------------------------------------- #
# Thin calls
# --------------------------------------------------------------------------- #
def _seed_login(captured):
    captured.responses.append(FakeResp(200, {"data": {"accessToken": "T", "expiresIn": 600}}))


def test_register_invoice_hits_register_path(merchant, secrets, captured):
    _seed_login(captured)
    captured.responses.append(FakeResp(200, {"statusCode": 200, "body": {"irn": "I"}}))
    mor_client.register_invoice(merchant, secrets, {"TransactionType": "B2C"})
    assert captured.calls[1]["url"].endswith("/v1/register")


def test_cancel_uses_capital_irn_and_validates_reason(merchant, secrets, captured):
    _seed_login(captured)
    captured.responses.append(FakeResp(200, {"statusCode": 200}))
    mor_client.cancel_invoice(merchant, secrets, "IRN9", 3, "oops")
    req = json.loads(captured.calls[1]["data"].decode("utf-8"))["request"]
    assert captured.calls[1]["url"].endswith("/v1/cancel")
    assert list(req.keys()) == ["Irn", "ReasonCode", "Remark"]
    assert req["Irn"] == "IRN9"
    assert req["ReasonCode"] == "3"  # coerced to string


@pytest.mark.parametrize("bad", [0, 5, "9", "x", -1])
def test_cancel_rejects_bad_reason_code(merchant, secrets, captured, bad):
    with pytest.raises(ValueError):
        mor_client.cancel_invoice(merchant, secrets, "IRN", bad, "r")
    assert captured.calls == []  # no network call made


@pytest.mark.parametrize("code", ["1", "2", "3", "4", 1, 2, 3, 4])
def test_cancel_accepts_valid_reason_codes(merchant, secrets, captured, code):
    _seed_login(captured)
    captured.responses.append(FakeResp(200, {"statusCode": 200}))
    mor_client.cancel_invoice(merchant, secrets, "IRN", code, "r")
    req = json.loads(captured.calls[1]["data"].decode("utf-8"))["request"]
    assert req["ReasonCode"] == str(code)


def test_verify_uses_lowercase_irn(merchant, secrets, captured):
    _seed_login(captured)
    captured.responses.append(FakeResp(200, {"statusCode": 200, "body": {}}))
    mor_client.verify_invoice(merchant, secrets, "IRN7")
    req = json.loads(captured.calls[1]["data"].decode("utf-8"))["request"]
    assert captured.calls[1]["url"].endswith("/v1/verify")
    assert list(req.keys()) == ["irn"]  # lowercase
    assert req["irn"] == "IRN7"


def test_register_receipt_hits_receipt_path(merchant, secrets, captured):
    _seed_login(captured)
    captured.responses.append(FakeResp(200, {"statusCode": 200, "body": {"rrn": "R1"}}))
    parsed = mor_client.register_receipt(merchant, secrets, {"ReceiptNumber": "REC-1"})
    assert captured.calls[1]["url"].endswith("/v1/receipt/sales")
    assert parsed["body"]["rrn"] == "R1"


def test_signed_body_matches_crypto_builder(merchant, secrets, captured, priv_key):
    """signed_post envelope == app.crypto.build_signed_body output (byte-exact)."""
    _seed_login(captured)
    captured.responses.append(FakeResp(200, {"statusCode": 200}))
    obj = {"b": 1, "a": 2}
    mor_client.signed_post(merchant, secrets, "/v1/register", obj)
    expected = build_signed_body(obj, priv_key, "already-base64-cert")
    assert captured.calls[1]["data"] == expected
