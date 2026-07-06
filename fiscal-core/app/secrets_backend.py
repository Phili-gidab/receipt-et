"""Secrets resolution abstraction (spec §6).

Merchant credentials (client_secret, api_key) and the private key / certificate
are NEVER stored as plaintext in the database — only references are. This module
resolves those references to actual values via a pluggable backend:

  * EnvSecrets        — local/dev. A ref is either an environment variable name
                        or, if it points at an existing file path, the file's
                        contents. Default backend ('env').
  * AwsSecretsManager — cloud. A ref is an AWS Secrets Manager secret id (the
                        SecretString is returned).

Public surface (what downstream code imports):

    SecretsBackend (ABC)
        get_secret(ref) -> str
        load_merchant_credentials(merchant) -> dict
        resolve_private_key(ref) -> RSAPrivateKey
        resolve_certificate(ref) -> str   # PEM (or base64) text

    get_secrets_backend(settings=None) -> SecretsBackend   # factory, default 'env'

``load_merchant_credentials`` returns a dict shaped::

    {
        "client_id":     str | None,   # taken verbatim from the row (an id, not a secret)
        "client_secret": str | None,   # resolved from the ref
        "api_key":       str | None,   # resolved from the ref
        "private_key":   RSAPrivateKey | None,
        "certificate":   str | None,   # PEM/base64 text
    }
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from app.config import Settings, get_settings
from app.crypto import load_private_key_from_pem

if TYPE_CHECKING:  # avoid hard import cycles / heavy deps at module import time
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

    from app.models import Merchant


class SecretsBackend(ABC):
    """Resolve credential references to values."""

    @abstractmethod
    def get_secret(self, ref: str) -> str:
        """Resolve a single reference to its string value."""

    def resolve_private_key(self, ref: str) -> "RSAPrivateKey":
        """Resolve ``ref`` to PEM text and load it as an RSA private key object."""
        pem = self.get_secret(ref)
        return load_private_key_from_pem(pem)

    def resolve_certificate(self, ref: str) -> str:
        """Resolve ``ref`` to the certificate PEM (or base64) text."""
        return self.get_secret(ref)

    def load_merchant_credentials(self, merchant: "Merchant") -> dict[str, Any]:
        """Resolve all credential refs on a merchant into usable values.

        Reads the merchant's ``secret`` relationship. ``client_id`` is an
        identifier (not a secret) and is passed through verbatim; the secret
        values and key/cert are resolved through this backend. Missing refs
        yield ``None`` for that field rather than raising, so a partially
        configured merchant can still be inspected.
        """
        secret = getattr(merchant, "secret", None)
        if secret is None:
            return {
                "client_id": None,
                "client_secret": None,
                "api_key": None,
                "private_key": None,
                "certificate": None,
            }

        def _maybe(ref: str | None) -> str | None:
            return self.get_secret(ref) if ref else None

        private_key = None
        if secret.private_key_ref:
            private_key = self.resolve_private_key(secret.private_key_ref)

        certificate = None
        if secret.certificate_ref:
            certificate = self.resolve_certificate(secret.certificate_ref)

        return {
            "client_id": secret.client_id,
            "client_secret": _maybe(secret.client_secret),
            "api_key": _maybe(secret.api_key),
            "private_key": private_key,
            "certificate": certificate,
        }


class EnvSecrets(SecretsBackend):
    """Local/dev backend.

    A reference is resolved in this order:
      1. If it names an existing file path -> the file's UTF-8 contents.
      2. Else if it names a set environment variable -> that variable's value.
         (Convention: a ``file://`` prefix forces file mode; an ``env:`` prefix
         forces env-var mode.)
      3. Else the reference is returned as-is (it may already be the literal
         value, e.g. a base64 cert pasted into the DB during dev).
    """

    def get_secret(self, ref: str) -> str:
        if ref is None:
            raise ValueError("EnvSecrets.get_secret called with None ref")

        if ref.startswith("file://"):
            path = ref[len("file://"):]
            return self._read_file(path)
        if ref.startswith("env:"):
            name = ref[len("env:"):]
            return self._read_env(name)

        # Bare ref: prefer a file if it exists, then an env var, else literal.
        if os.path.isfile(ref):
            return self._read_file(ref)
        if ref in os.environ:
            return os.environ[ref]
        return ref

    @staticmethod
    def _read_file(path: str) -> str:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    @staticmethod
    def _read_env(name: str) -> str:
        try:
            return os.environ[name]
        except KeyError as exc:
            raise KeyError(f"Secret env var not set: {name}") from exc


class AwsSecretsManager(SecretsBackend):
    """Cloud backend backed by AWS Secrets Manager.

    A reference is a Secrets Manager secret id (name or ARN). The boto3 client
    is created lazily so importing this module does not require AWS to be
    configured.
    """

    def __init__(self, region_name: str) -> None:
        self.region_name = region_name
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3  # lazy import — only needed when AWS backend is active

            self._client = boto3.client("secretsmanager", region_name=self.region_name)
        return self._client

    def get_secret(self, ref: str) -> str:
        if ref is None:
            raise ValueError("AwsSecretsManager.get_secret called with None ref")
        resp = self._get_client().get_secret_value(SecretId=ref)
        secret = resp.get("SecretString")
        if secret is None:
            # Binary secret — decode to text.
            import base64

            secret = base64.b64decode(resp["SecretBinary"]).decode("utf-8")
        return secret


def get_secrets_backend(settings: Settings | None = None) -> SecretsBackend:
    """Factory: build the configured backend. Defaults to EnvSecrets ('env')."""
    settings = settings or get_settings()
    if settings.SECRETS_BACKEND == "aws":
        return AwsSecretsManager(region_name=settings.AWS_REGION)
    return EnvSecrets()
