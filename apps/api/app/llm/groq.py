from __future__ import annotations

from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider as _GroqProvider
from pydantic_ai.settings import ModelSettings

from app.config import settings

GROQ_MODEL = "llama-3.3-70b-versatile"


class GroqProvider:
    """Fallback provider — Groq's hosted Llama 3.3 70B."""

    name = "groq"

    def model(self) -> GroqModel:
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set; cannot build Groq model.")
        provider = _GroqProvider(api_key=settings.groq_api_key)
        return GroqModel(
            GROQ_MODEL,
            provider=provider,
            settings=ModelSettings(max_tokens=2048),
        )
