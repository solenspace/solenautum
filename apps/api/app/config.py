from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    clerk_secret_key: str = Field(..., alias="CLERK_SECRET_KEY")
    clerk_publishable_key: str = Field(..., alias="CLERK_PUBLISHABLE_KEY")

    autumn_user_agent: str = Field(
        default="AutumnBot/0.1 (+https://github.com/mtohernandez/autumn)",
        alias="AUTUMN_USER_AGENT",
    )

    autumn_url_allowlist: str | None = Field(
        default=None,
        alias="AUTUMN_URL_ALLOWLIST",
        description="Comma-separated domain patterns. None disables the allow-list.",
    )

    # Postgres (Neon). Optional so the app boots without a configured DB;
    # the engine factory in app/persistence/db.py raises on first use if unset.
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    database_url_unpooled: str | None = Field(default=None, alias="DATABASE_URL_UNPOOLED")

    # Blob store. `local` writes to apps/api/data/snapshots/ for dev/tests;
    # `r2` requires the four R2_* credentials below.
    blob_store_backend: Literal["r2", "local"] = Field(default="local", alias="BLOB_STORE_BACKEND")
    r2_account_id: str | None = Field(default=None, alias="R2_ACCOUNT_ID")
    r2_access_key_id: str | None = Field(default=None, alias="R2_ACCESS_KEY_ID")
    r2_secret_access_key: str | None = Field(default=None, alias="R2_SECRET_ACCESS_KEY")
    r2_bucket: str | None = Field(default=None, alias="R2_BUCKET")

    # Clerk webhook. Optional so test envs boot without a secret;
    # the webhook route returns 503 at request time when unset.
    clerk_webhook_signing_secret: str | None = Field(
        default=None, alias="CLERK_WEBHOOK_SIGNING_SECRET"
    )

    # LLM providers. Optional so the api boots without keys; the chain raises
    # at first call. The provider chain switches OpenRouter -> Groq on 429/5xx
    # only (invariant 12).
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")

    # Langfuse. Optional so dev/CI runs without observability; the client is
    # constructed with `enabled=False` when keys are missing so spans are no-ops.
    langfuse_public_key: str | None = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str | None = Field(default=None, alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        alias="LANGFUSE_HOST",
    )

    @property
    def allowlist_patterns(self) -> tuple[str, ...]:
        if not self.autumn_url_allowlist:
            return ()
        return tuple(p.strip() for p in self.autumn_url_allowlist.split(",") if p.strip())


settings = Settings()
