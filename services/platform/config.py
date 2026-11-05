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

    # "otp": mobile number + one-time code, session in an HttpOnly cookie (services/platform/signin.py).
    # "oidc": bearer tokens from an identity provider. "dev": also trusts X-Dev-* headers so tests and
    # tooling can act as any seeded identity; refused in production by the validator below.
    # In dev mode a signed-in session cookie is honoured too, so the web app uses real sign-in.
    auth_mode: Literal["dev", "otp", "oidc"] = "dev"
    session_secret: str = "dev-only-session-secret-change-me-0000000000"  # noqa: S105  refused in prod
    session_hours: int = 12
    # How one-time codes are delivered. "log" writes them to the server log (development only).
    sms_provider: Literal["log"] = "log"
    # Appointment emails (services/notifications). "log" records the message in the server log only;
    # "smtp" sends through any SMTP server (Mailpit in development: `make up`, inbox at :8025).
    email_provider: Literal["log", "smtp"] = "log"
    email_from: str = "MedPal <appointments@medpal.local>"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = False
    # Who sends due messages: "inline" (a loop inside the API; one process or many, rows are claimed
    # with SKIP LOCKED), "worker" (the arq worker's schedule) or "off".
    notify_dispatch: Literal["inline", "worker", "off"] = "inline"
    notify_poll_seconds: float = 15.0
    # Links in emails (confirm address, manage appointments) point here.
    public_base_url: str = "http://localhost:8000"
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
    # Reasoning effort for models that "think" (Gemini thinking levels; ignored by other providers).
    # Routing labels need little; drafting and cited answers may want more. Unset = provider default.
    chat_thinking_level: Literal["low", "medium", "high"] | None = None
    # Every provider attempt has a hard deadline; a timeout is a provider failure (next in the chain, then
    # a safe "unavailable"). SDK retries stay low so one call can't stretch into minutes of backoff.
    chat_timeout_seconds: float = 30.0
    chat_max_retries: int = 1
    # Which tier answers records questions: "large" (default) or "small" when latency matters more.
    # Decide with `make live-check` (quality) and `make load-test` (p95) on your own models.
    records_model_tier: Literal["small", "large"] = "large"
    # Triage's model check (red-flag second pass + specialty guess) waits at most this long; past it,
    # triage continues on the rules and the patient's explicit safety answers.
    triage_model_deadline_seconds: float = 4.0
    chat_small_thinking_level: Literal["low", "medium", "high"] | None = None
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
        weak_secret = len(self.session_secret) < 32 or self.session_secret.startswith("dev-only")
        if self.env == "prod" and self.auth_mode == "otp" and weak_secret:
            raise ValueError("production requires a random MEDPAL_SESSION_SECRET of at least 32 characters")
        if self.env == "prod" and self.auth_mode == "otp" and self.sms_provider == "log":
            raise ValueError("production sign-in by mobile needs a real SMS provider, not the log")
        if self.chat_fallback_provider and not self.chat_fallback_model:
            raise ValueError("chat_fallback_model is required when chat_fallback_provider is set")
        if self.env == "prod" and self.chat_provider == "fake":
            raise ValueError("chat_provider=fake is not allowed when env=prod")
        if self.env == "prod" and self.object_store_backend != "s3":
            raise ValueError("production requires object_store_backend=s3")
        if self.env == "prod" and self.notify_dispatch != "off" and self.email_provider == "log":
            raise ValueError(
                "production appointment emails need a real email provider (MEDPAL_EMAIL_PROVIDER=smtp)"
            )
        return self

    @property
    def migration_sqlalchemy_url(self) -> str:
        return self.migration_database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
