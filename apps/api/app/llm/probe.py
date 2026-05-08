from __future__ import annotations

import structlog

from app.config import settings

log = structlog.get_logger()


async def probe_providers() -> None:
    """One-shot startup probe. Logs presence of LLM credentials so a missing
    `.env` is visible at boot rather than at first mission. Does **not** fire a
    completion — free-tier rate-limits are too tight to spend tokens on a probe.
    Real availability surfaces on the first run, where `LLMProviderChain`
    handles 429/5xx by falling back (invariant 12).
    """
    for name, key in (
        ("openrouter", settings.openrouter_api_key),
        ("groq", settings.groq_api_key),
    ):
        status = "configured" if key else "missing"
        log.info("llm.provider.probe", provider=name, status=status)

    if settings.langfuse_public_key and settings.langfuse_secret_key:
        log.info("langfuse.probe", status="configured", host=settings.langfuse_host)
    else:
        log.info("langfuse.probe", status="missing")
