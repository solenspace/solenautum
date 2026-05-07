from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.jobs.orphan_reaper import orphan_reaper_loop
from app.jobs.selector_sweep import selector_sweep_loop
from app.llm.probe import probe_providers
from app.routes import router as api_router
from app.security import RequireUser, limiter
from app.sse import emitter

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup probe surfaces missing LLM/Langfuse credentials in the boot
    log. Failures are non-fatal so the api still boots in environments
    without keys (the chain raises at first call instead).

    Wraps the yield region in an `asyncio.TaskGroup` and binds it to the
    SSE emitter so `MissionRunner` instances spawned by `POST /missions`
    are owned by a structured-concurrency parent (invariant 3). On
    shutdown, the group awaits every in-flight runner to settle before
    the process exits — no detached tasks, no orphaned browser sessions.
    """
    try:
        await probe_providers()
    except Exception as exc:  # pragma: no cover — probe must never crash boot
        log.warning("startup.probe_failed", extra={"error": str(exc)})
    async with asyncio.TaskGroup() as tg:
        emitter.bind_lifespan_tg(tg)
        # Spec 13: TTL sweep over `saved_selectors` runs every 6h. Owned
        # by the lifespan group so shutdown cancels it via CancelledError.
        tg.create_task(selector_sweep_loop(), name="selector-sweep")
        # Spec 14: orphan-mission reaper runs every 5min and cancels
        # missions stuck in pending or awaiting_approval past the 1h
        # threshold. Same lifespan ownership as the selector sweep.
        tg.create_task(orphan_reaper_loop(), name="orphan-reaper")
        yield


app = FastAPI(title="Autumn API", lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.include_router(api_router)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(
    request: Request,  # noqa: ARG001  # FastAPI exception-handler signature
    exc: RateLimitExceeded,
) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "rate limit exceeded", "retry_after": str(exc.detail)},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/me")
@limiter.limit("60/minute")
async def me(
    request: Request,  # noqa: ARG001  # slowapi keys off the parameter named "request"
    user: RequireUser,
) -> dict[str, str]:
    return {"user_id": user.user_id}
