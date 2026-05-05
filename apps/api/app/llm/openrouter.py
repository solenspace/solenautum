from __future__ import annotations

from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from app.config import settings

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "openai/gpt-oss-120b:free"


class OpenRouterProvider:
    """Primary provider — OpenAI-compatible OpenRouter free-tier model."""

    name = "openrouter"

    def model(self) -> OpenAIModel:
        if not settings.openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set; cannot build OpenRouter model.",
            )
        provider = OpenAIProvider(
            base_url=OPENROUTER_BASE_URL,
            api_key=settings.openrouter_api_key,
        )
        return OpenAIModel(
            OPENROUTER_MODEL,
            provider=provider,
            settings=ModelSettings(max_tokens=2048),
        )
