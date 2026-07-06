"""Application settings (pydantic-settings).

Read from environment variables / a local ``.env`` file. This holds ONLY
service-level/infrastructure configuration. It deliberately contains NO fiscal
values (TIN, system type/number, certificates, keys, credentials, seller
details, tax codes, invoice chain) — those are per-merchant state stored in the
database and resolved from the secrets backend. See MOR_EIMS_CONTRACT.md §0/§6.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration loaded from env / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Postgres connection string. Default points at a local dev database.
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/receipt"

    # Where merchant secrets (client_secret, api_key, private key, certificate)
    # are resolved from. 'env' = environment variables / files (local dev);
    # 'aws' = AWS Secrets Manager (cloud). Default 'env'.
    SECRETS_BACKEND: Literal["env", "aws"] = "env"

    # AWS region used by the AwsSecretsManager backend (and boto3 in general).
    AWS_REGION: str = "us-east-1"

    # Deployment environment. Influences defaults like TLS verification.
    ENV: Literal["sandbox", "prod"] = "sandbox"

    # Standard Python logging level name.
    LOG_LEVEL: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (single read of env per process)."""
    return Settings()
