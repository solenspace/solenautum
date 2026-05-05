from __future__ import annotations

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

    @property
    def allowlist_patterns(self) -> tuple[str, ...]:
        if not self.autumn_url_allowlist:
            return ()
        return tuple(p.strip() for p in self.autumn_url_allowlist.split(",") if p.strip())


settings = Settings()
