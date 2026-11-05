"""Runtime settings. Values come from environment variables or a local .env (never committed)."""

from datetime import date
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MEDPAL_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"

    # The application connects as a NON-superuser role so Postgres row-level security applies
    # (superusers bypass RLS entirely). Migrations and seeding use the owner role.
    database_url: str = "postgresql://medpal_app:medpal_app@localhost:5433/medpal"
    migration_database_url: str = "postgresql://medpal:medpal@localhost:5433/medpal"
    # LangGraph checkpoint tables live in their own schema (ADR-0001: each module owns its schema).
    checkpoint_schema: str = "langgraph"
    db_pool_max_size: int = 10

    # "dev" trusts X-Dev-* headers so the stack runs before OIDC login (Keycloak) is added.
    # It is refused outside dev/test by the validator below.
    auth_mode: Literal["dev", "oidc"] = "dev"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None

    # Hosted generation goes through services.platform.egress, which de-identifies first.
    # `fake` is deterministic and exists for local tests only; production must pick a provider.
    chat_provider: Literal["fake", "gemini", "openai", "anthropic", "openai-compatible"] = "fake"
    chat_model: str = "medpal-fake"
    chat_api_key: str | None = None
    chat_base_url: str | None = None
    chat_temperature: float = 0.0
    # Model routing: a smaller model for classification-style steps (defaults to the primary model).
    chat_small_model: str | None = None
    # Fallback provider, tried when the primary fails or returns invalid output.
    chat_fallback_provider: Literal["fake", "gemini", "openai", "anthropic", "openai-compatible"] | None = (
        None
    )
    chat_fallback_model: str | None = None
    chat_fallback_api_key: str | None = None
    chat_fallback_base_url: str | None = None

    speech_model_path: str | None = None

    # Cost metering: price per million tokens by model id, e.g.
    # MEDPAL_MODEL_PRICES='{"gemini-2.5-flash": {"in": 0.30, "out": 2.50}}'. Never hard-coded in the code;
    # always stamped with the date the price list was read. Unpriced models report cost as NULL.
    model_prices: dict[str, dict[str, float]] = {}
    price_list_date: date | None = None
    price_currency: str = "USD"

    # Records ingest: "inline" runs in the upload request (local dev, tests); "queue" hands the document
    # id to the arq worker. Only the id goes to Redis, never document content.
    ingest_mode: Literal["inline", "queue"] = "inline"
    ingest_max_concurrency: int = 4  # pages processed in parallel per document
    redis_url: str = "redis://localhost:6380"

    # Pharmacy stock feed for the worker's scheduled sync: "none" (stock loaded by the seed),
    # "csv" (nightly file) or "api" (real-time pharmacy API). Same interface either way.
    pharmacy_feed: Literal["none", "csv", "api"] = "none"
    pharmacy_feed_path: str | None = None
    pharmacy_api_url: str | None = None
    pharmacy_api_token: str | None = None

    object_store_backend: Literal["file", "s3", "memory"] = "file"
    object_store_directory: str = ".medpal/objects"
    object_store_region: str = "ap-south-1"
    object_store_bucket: str = "medpal-records"
    object_store_endpoint_url: str | None = None
    object_store_access_key_id: str | None = None
    object_store_secret_access_key: str | None = None

    @model_validator(mode="after")
    def _no_dev_auth_in_prod(self) -> "Settings":
        if self.env == "prod" and self.auth_mode == "dev":
            raise ValueError("auth_mode=dev is not allowed when env=prod")
        if self.chat_fallback_provider and not self.chat_fallback_model:
            raise ValueError("chat_fallback_model is required when chat_fallback_provider is set")
        if self.env == "prod" and self.chat_provider == "fake":
            raise ValueError("chat_provider=fake is not allowed when env=prod")
        if self.env == "prod" and self.object_store_backend != "s3":
            raise ValueError("production requires object_store_backend=s3")
        return self

    @property
    def migration_sqlalchemy_url(self) -> str:
        return self.migration_database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
