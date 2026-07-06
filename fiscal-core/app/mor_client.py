"""MoR EIMS transport + auth layer (sync, multi-tenant).

Ported from the sandbox-validated Delta implementation
(Delta_SPMU/backend/frappe-lms/lms/lms/eims.py lines 314-422) and rewritten to
be **per-merchant / pure** per MOR_EIMS_CONTRACT.md §0-§3. Where Delta read one
set of global ``frappe.conf`` keys, this module takes the merchant + resolved
secrets as arguments and reads no global fiscal config.

What lives here (and only here):

  * ``_post_raw``       — the raw HTTP POST (requests, sync, raw bytes, 60s).
  * a per-merchant in-process token cache (TTL dict keyed by merchant id).
  * ``login`` / ``get_token`` — auth against ``/auth/login`` (spec §1).
  * ``signed_post``    — sign (via app.crypto) + POST + one 401 re-login retry.
  * thin call wrappers — register / cancel / verify invoice + register receipt.

The signing/canonicalisation/envelope logic is NOT duplicated here; it is
imported from :mod:`app.crypto` (``build_signed_body``), which is the verbatim
port of the spec §0 transport invariants. This module is the transport +
session layer on top of it.

Arguments
---------
``merchant``
    An :class:`app.models.Merchant` (or any object exposing ``id``, ``tin``,
    ``base_url``, ``tls_verify``). Provides the per-tenant endpoint + TLS toggle
    and the TIN sent in the login body.
``secrets``
    The resolved credentials dict from
    :meth:`app.secrets_backend.SecretsBackend.load_merchant_credentials`, i.e.::

        {
            "client_id":     str | None,
            "client_secret": str | None,
            "api_key":       str | None,
            "private_key":   RSAPrivateKey | None,
            "certificate":   str | None,   # PEM/base64 text
        }

    The private key object and certificate text are passed straight into
    :func:`app.crypto.build_signed_body` — this module never loads keys itself.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

import requests

from app.crypto import build_signed_body

__all__ = [
    "MorClientError",
    "MorAuthError",
    "MorTransportError",
    "AUTH_KEY_MAP",
    "AUTH_KEY_MAP_LOWERCASE",
    "PATH_LOGIN",
    "PATH_REGISTER",
    "PATH_CANCEL",
    "PATH_VERIFY",
    "PATH_RECEIPT_SALES",
    "TOKEN_TTL_FALLBACK",
    "VALID_CANCEL_REASON_CODES",
    "clear_token_cache",
    "_post_raw",
    "login",
    "get_token",
    "signed_post",
    "register_invoice",
    "cancel_invoice",
    "verify_invoice",
    "register_receipt",
]

# ---------------------------------------------------------------------------
# Constants (spec §0)
# ---------------------------------------------------------------------------
# Endpoints, appended to the merchant's base URL.
PATH_LOGIN = "/auth/login"
PATH_REGISTER = "/v1/register"
PATH_CANCEL = "/v1/cancel"
PATH_VERIFY = "/v1/verify"
PATH_RECEIPT_SALES = "/v1/receipt/sales"

# Token TTL fallback (seconds) when the login response omits ``expiresIn``.
TOKEN_TTL_FALLBACK = 3000

# 60s timeout on every call (spec §0).
HTTP_TIMEOUT = 60

# Cancel ReasonCode whitelist (spec §3 / DO-NOT-INHERIT #7).
VALID_CANCEL_REASON_CODES = {"1", "2", "3", "4"}

# ---------------------------------------------------------------------------
# Auth key casing — CONFIGURABLE (spec §1 casing caveat / DO-NOT-INHERIT #2).
# ---------------------------------------------------------------------------
# camelCase ``clientId``/``clientSecret`` worked in sandbox 2026-06-12; the auth
# *schema text* (Draft l.4102-4124) may instead want all-lowercase keys. The
# login body is built from a {logical_field -> wire_key} map so the casing can be
# flipped (e.g. on a 4xx) by passing ``key_map=AUTH_KEY_MAP_LOWERCASE`` to
# ``login`` without touching any other code. The logical field order is
# preserved (clientId, clientSecret, apikey, tin) so the canonical/signed body
# matches the sandbox-proven ordering.

# Default: sandbox-PROVEN camelCase (2026-06-12).
AUTH_KEY_MAP: dict[str, str] = {
    "client_id": "clientId",
    "client_secret": "clientSecret",
    "api_key": "apikey",
    "tin": "tin",
}

# Fallback: all-lowercase per the auth schema text; flip to this on a 4xx.
AUTH_KEY_MAP_LOWERCASE: dict[str, str] = {
    "client_id": "clientid",
    "client_secret": "clientsecret",
    "api_key": "apikey",
    "tin": "tin",
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class MorClientError(Exception):
    """Base error for the MoR transport/auth layer."""


class MorTransportError(MorClientError):
    """Network-level failure talking to MoR (timeout / connection / HTTP)."""


class MorAuthError(MorClientError):
    """Authentication failed (no ``data.accessToken`` in the login response)."""


# ---------------------------------------------------------------------------
# Per-merchant token cache (in-process TTL dict, keyed by merchant id).
# ---------------------------------------------------------------------------
# NOTE (multi-worker caveat): this cache is PER PROCESS. Each uvicorn/gunicorn
# worker (and each box, in a horizontally-scaled deployment) holds its own copy,
# so the same merchant may be logged in N times concurrently and a forced
# re-login in one worker does not evict the others. That is acceptable — MoR
# issues independent bearer tokens and the chain is serialised separately by the
# Postgres advisory lock (spec §6) — but if a single shared session is ever
# required, back this with Redis (as Delta did via ``frappe.cache()``). The lock
# only guards this process's dict; it does NOT coordinate across workers.
_TOKEN_CACHE: dict[int, dict[str, Any]] = {}
_TOKEN_CACHE_LOCK = threading.Lock()


def _cache_get(merchant_id: int) -> Optional[str]:
    """Return a cached, non-expired access token for ``merchant_id`` or None."""
    with _TOKEN_CACHE_LOCK:
        entry = _TOKEN_CACHE.get(merchant_id)
        if not entry:
            return None
        if entry["expires_at"] <= time.monotonic():
            # Expired — drop it so we don't keep re-checking.
            _TOKEN_CACHE.pop(merchant_id, None)
            return None
        return entry["token"]


def _cache_set(merchant_id: int, token: str, ttl: int, encryption_key: Optional[str]) -> None:
    """Store a token (and optional encryptionKey) for ``merchant_id`` for ``ttl`` s."""
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE[merchant_id] = {
            "token": token,
            "encryption_key": encryption_key,
            "expires_at": time.monotonic() + ttl,
        }


def _cache_get_encryption_key(merchant_id: int) -> Optional[str]:
    """Return the cached encryptionKey for ``merchant_id`` (or None)."""
    with _TOKEN_CACHE_LOCK:
        entry = _TOKEN_CACHE.get(merchant_id)
        if not entry or entry["expires_at"] <= time.monotonic():
            return None
        return entry.get("encryption_key")


def _cache_clear(merchant_id: int) -> None:
    """Evict any cached token for ``merchant_id``."""
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE.pop(merchant_id, None)


def clear_token_cache(merchant_id: Optional[int] = None) -> None:
    """Evict cached tokens. Pass a merchant id, or None to clear the whole cache.

    Public helper for tests / admin reset.
    """
    if merchant_id is None:
        with _TOKEN_CACHE_LOCK:
            _TOKEN_CACHE.clear()
    else:
        _cache_clear(merchant_id)


# ---------------------------------------------------------------------------
# Small accessors over the merchant / secrets inputs (no globals).
# ---------------------------------------------------------------------------
def _base_url(merchant: Any) -> str:
    base = getattr(merchant, "base_url", None)
    if not base:
        raise MorClientError(
            f"Merchant {getattr(merchant, 'tin', '?')} has no base_url configured."
        )
    return str(base).rstrip("/")


def _tls_verify(merchant: Any) -> bool:
    """Per-merchant TLS verification toggle (spec §0). Defaults to True."""
    val = getattr(merchant, "tls_verify", True)
    return True if val is None else bool(val)


def _merchant_id(merchant: Any) -> int:
    mid = getattr(merchant, "id", None)
    if mid is None:
        raise MorClientError("Merchant has no id (required for the token cache).")
    return int(mid)


# ---------------------------------------------------------------------------
# HTTP transport (spec §0)
# ---------------------------------------------------------------------------
def _post_raw(
    base_url: str,
    path: str,
    body_bytes: bytes,
    token: Optional[str],
    tls_verify: bool,
) -> tuple[int, Any]:
    """POST raw ``body_bytes`` to ``base_url + path``; return (status, parsed_json).

    Sends the body as RAW BYTES (``data=``), never ``json=`` (spec §0 exact-bytes
    rule — the canonical signed string must be the exact bytes on the wire).
    ``Content-Type: application/json`` always; ``Authorization: Bearer <token>``
    only when ``token`` is provided (every call except ``/auth/login``). 60s
    timeout. If the response is not JSON, a synthetic dict is returned so callers
    always get a parsed object.
    """
    url = base_url + path
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.post(
            url,
            data=body_bytes,
            headers=headers,
            timeout=HTTP_TIMEOUT,
            verify=tls_verify,
        )
    except requests.exceptions.Timeout as exc:
        raise MorTransportError(f"EIMS request to {path} timed out.") from exc
    except requests.exceptions.ConnectionError as exc:
        raise MorTransportError(f"Could not connect to EIMS at {url}: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise MorTransportError(f"EIMS request to {path} failed: {exc}") from exc

    try:
        parsed = resp.json()
    except ValueError:
        parsed = {
            "statusCode": resp.status_code,
            "message": "NON_JSON_RESPONSE",
            "body": resp.text[:2000],
        }
    return resp.status_code, parsed


# ---------------------------------------------------------------------------
# Authentication (spec §1)
# ---------------------------------------------------------------------------
def _require_secret(secrets: dict[str, Any], field: str) -> Any:
    val = secrets.get(field)
    if val in (None, ""):
        raise MorAuthError(f"Merchant secret '{field}' is not set; cannot authenticate.")
    return val


def login(
    merchant: Any,
    secrets: dict[str, Any],
    key_map: dict[str, str] = AUTH_KEY_MAP,
) -> str:
    """Authenticate ``merchant`` against ``/auth/login`` and cache the token.

    Builds the login request object ``{clientId, clientSecret, apikey, tin}``
    (wire-key casing taken from ``key_map`` — flip to ``AUTH_KEY_MAP_LOWERCASE``
    on a 4xx, see DO-NOT-INHERIT #2). The body is signed with the merchant's
    private key/cert exactly like any other call (spec §0 — login is signed too).

    Reads ``data.accessToken`` (required), ``data.expiresIn`` (optional), and
    ``data.encryptionKey`` (optional). Caches the token per-merchant with
    ``ttl = max(60, expiresIn - 120)``; fallback 3000s if ``expiresIn`` absent.

    Returns the access token. Raises :class:`MorAuthError` if none is returned.
    """
    # Logical field order preserved -> canonical/signed body matches the
    # sandbox-proven ordering regardless of the wire-key casing chosen.
    request_obj = {
        key_map["client_id"]: _require_secret(secrets, "client_id"),
        key_map["client_secret"]: _require_secret(secrets, "client_secret"),
        key_map["api_key"]: _require_secret(secrets, "api_key"),
        key_map["tin"]: getattr(merchant, "tin", None),
    }

    body = build_signed_body(
        request_obj,
        _require_secret(secrets, "private_key"),
        _require_secret(secrets, "certificate"),
    )

    status, parsed = _post_raw(
        _base_url(merchant),
        PATH_LOGIN,
        body,
        token=None,  # login itself is unauthenticated (no Bearer header)
        tls_verify=_tls_verify(merchant),
    )

    data = (parsed or {}).get("data") or {}
    token = data.get("accessToken")
    if not token:
        msg = parsed.get("message") if isinstance(parsed, dict) else parsed
        raise MorAuthError(
            f"EIMS authentication failed for merchant "
            f"{getattr(merchant, 'tin', '?')} (HTTP {status}): {msg}"
        )

    # ttl = max(60, expiresIn - 120); fallback TOKEN_TTL_FALLBACK if absent.
    try:
        expires_in = int(data.get("expiresIn")) if data.get("expiresIn") is not None else None
    except (TypeError, ValueError):
        expires_in = None
    expires_in = expires_in or TOKEN_TTL_FALLBACK
    ttl = max(60, expires_in - 120)

    _cache_set(_merchant_id(merchant), token, ttl, data.get("encryptionKey"))
    return token


def get_token(
    merchant: Any,
    secrets: dict[str, Any],
    force: bool = False,
    key_map: dict[str, str] = AUTH_KEY_MAP,
) -> str:
    """Return a valid access token for ``merchant``, logging in if needed.

    Returns the cached token when present and unexpired, unless ``force`` is set
    (which drops the cache and re-logs-in).
    """
    if not force:
        cached = _cache_get(_merchant_id(merchant))
        if cached:
            return cached
    return login(merchant, secrets, key_map=key_map)


# ---------------------------------------------------------------------------
# Signed POST (spec §0/§1 — sign, POST, one 401 re-login retry)
# ---------------------------------------------------------------------------
def signed_post(
    merchant: Any,
    secrets: dict[str, Any],
    path: str,
    request_obj: Any,
    authed: bool = True,
    encrypt: bool = False,
    key_map: dict[str, str] = AUTH_KEY_MAP,
) -> Any:
    """Sign ``request_obj`` with the merchant's key/cert, POST it, return parsed.

    Builds the ``{request, signature, certificate}`` envelope via
    :func:`app.crypto.build_signed_body` (byte-exact). When ``authed`` (default),
    attaches a Bearer token from :func:`get_token`. On HTTP 401 it drops the
    cached token, re-logs-in (force), rebuilds the signed body, and POSTs **once**
    more (spec §1).

    ``encrypt`` is plumbed through for completeness but defaults OFF (spec §0 —
    sandbox 2026-06-12 confirmed ``/v1/register`` needs no encryption). When
    enabled, the signed body is AES-wrapped as ``{"data": <b64>}`` using the
    merchant's cached ``encryptionKey``; the real algorithm is unconfirmed, so do
    not enable without MoR sign-off.
    """
    private_key = _require_secret(secrets, "private_key")
    certificate = _require_secret(secrets, "certificate")
    tls_verify = _tls_verify(merchant)
    base_url = _base_url(merchant)
    mid = _merchant_id(merchant)

    def _make_body() -> bytes:
        body = build_signed_body(request_obj, private_key, certificate)
        if encrypt and authed:
            body = _wrap_encrypted(mid, body)
        return body

    token = get_token(merchant, secrets, key_map=key_map) if authed else None
    status, parsed = _post_raw(base_url, path, _make_body(), token, tls_verify)

    # Token expired / unauthorised -> re-login once and retry (spec §1).
    if status == 401 and authed:
        _cache_clear(mid)
        token = get_token(merchant, secrets, force=True, key_map=key_map)
        status, parsed = _post_raw(base_url, path, _make_body(), token, tls_verify)

    return parsed


def _wrap_encrypted(merchant_id: int, body: bytes) -> bytes:
    """Wrap a signed body as ``{"data": <b64>}`` (optional payload encryption).

    Best-guess AES-256-CBC via :func:`app.crypto.encrypt_payload`, keyed by the
    merchant's cached ``encryptionKey``. KEEP OFF by default (spec §0). Imported
    lazily so the encryption path has zero cost when it is never used.
    """
    import json

    from app.crypto import encrypt_payload

    enc_key = _cache_get_encryption_key(merchant_id) or ""
    return json.dumps({"data": encrypt_payload(body, enc_key)}).encode("utf-8")


# ---------------------------------------------------------------------------
# Thin call wrappers (spec §2/§3/§5)
# ---------------------------------------------------------------------------
def register_invoice(
    merchant: Any,
    secrets: dict[str, Any],
    obj: Any,
    encrypt: bool = False,
) -> Any:
    """POST a pre-built invoice/note object to ``/v1/register`` (spec §2/§4).

    ``obj`` is the canonical MoR invoice dict assembled by the request builder
    from merchant state (this layer does NOT build it — it only signs + sends).
    Returns the parsed response (success path reads ``statusCode == 200`` and
    ``body.irn``).
    """
    return signed_post(merchant, secrets, PATH_REGISTER, obj, authed=True, encrypt=encrypt)


def cancel_invoice(
    merchant: Any,
    secrets: dict[str, Any],
    irn: str,
    reason_code: Any,
    remark: str = "",
) -> Any:
    """Cancel a registered invoice via ``/v1/cancel`` (spec §3).

    Sends ``{"Irn": <irn>, "ReasonCode": <"1".."4">, "Remark": <text>}`` —
    capital ``Irn`` here (contrast verify's lowercase ``irn``). ``reason_code`` is
    coerced to a string and validated against {1,2,3,4} (DO-NOT-INHERIT #7);
    invalid codes raise :class:`ValueError` before any network call.
    """
    code = str(reason_code)
    if code not in VALID_CANCEL_REASON_CODES:
        raise ValueError(
            f"Invalid cancel ReasonCode {reason_code!r}; must be one of "
            f"{sorted(VALID_CANCEL_REASON_CODES)} "
            f"(1=Duplicate, 2=Data-entry mistake, 3=Order Cancelled, 4=Others)."
        )
    request_obj = {"Irn": irn, "ReasonCode": code, "Remark": remark or ""}
    return signed_post(merchant, secrets, PATH_CANCEL, request_obj, authed=True)


def verify_invoice(merchant: Any, secrets: dict[str, Any], irn: str) -> Any:
    """Look up a registered invoice via ``/v1/verify`` (spec §3).

    Sends ``{"irn": <irn>}`` — LOWERCASE ``irn`` here (contrast cancel's capital
    ``Irn``).
    """
    return signed_post(merchant, secrets, PATH_VERIFY, {"irn": irn}, authed=True)


def register_receipt(
    merchant: Any,
    secrets: dict[str, Any],
    obj: Any,
) -> Any:
    """POST a pre-built sales-receipt object to ``/v1/receipt/sales`` (spec §5).

    ``obj`` is the canonical receipt dict assembled by the receipt builder.
    Sandbox-UNVALIDATED (spec §5); success reads ``body.rrn``.
    """
    return signed_post(merchant, secrets, PATH_RECEIPT_SALES, obj, authed=True)
