from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.jobs.orphan_reaper import orphan_reaper_loop
from app.jobs.selector_sweep import selector_sweep_loop
from app.llm.probe import probe_providers
from app.logging import configure_logging
from app.persistence.blob import get_blob_store
from app.persistence.db import _get_engine
from app.routes import router as api_router
from app.security import RequireUser, limiter
from app.sse import emitter

configure_logging()

log = structlog.get_logger()


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
        log.warning("startup.probe_failed", error=str(exc))
    try:
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
    finally:
        # Pair `bind_lifespan_tg`. Without this, `pytest` runs that spin
        # the lifespan up/down across multiple `TestClient` contexts hit
        # the rebind guard on the second startup and deadlock.
        emitter.unbind_lifespan_tg()


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


# `api.clerk.com/.well-known/jwks.json` is a 404 — JWKS lives on the
# per-instance Frontend API, not the central Backend API.
_CLERK_HEALTH_URL = "https://api.clerk.com/v1/health"
# Total readiness budget stays under Fly's 5s probe `timeout`.
_PG_TIMEOUT_S = 0.5
_R2_TIMEOUT_S = 1.0
_CLERK_TIMEOUT_S = 2.0

ProbeStatus = Literal["ok", "down"]


async def _safe_probe(
    name: str, timeout_s: float, body: Callable[[], Awaitable[None]]
) -> tuple[str, ProbeStatus]:
    try:
        async with asyncio.timeout(timeout_s):
            await body()
        return name, "ok"
    except Exception:
        log.exception(f"readiness.{name}_failed")
        return name, "down"


async def _probe_postgres() -> None:
    async with _get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _probe_clerk() -> None:
    async with httpx.AsyncClient() as client:
        response = await client.get(_CLERK_HEALTH_URL)
        response.raise_for_status()


@app.get("/health/ready")
async def ready() -> dict[str, Any]:
    """Returns 200 only when every downstream is reachable. Fly's
    `[[http_service.checks]]` routes new traffic away from this replica on
    503. Probes run concurrently — worst-case latency is the slowest single
    probe, not their sum.
    """
    results = await asyncio.gather(
        _safe_probe("postgres", _PG_TIMEOUT_S, _probe_postgres),
        _safe_probe("blob", _R2_TIMEOUT_S, get_blob_store().health_check),
        _safe_probe("clerk", _CLERK_TIMEOUT_S, _probe_clerk),
    )
    checks: dict[str, ProbeStatus] = dict(results)
    if any(status != "ok" for status in checks.values()):
        raise HTTPException(status_code=503, detail={"checks": checks})
    return {"ok": True, "checks": checks}


@app.get("/me")
@limiter.limit("60/minute")
async def me(
    request: Request,  # noqa: ARG001  # slowapi keys off the parameter named "request"
    user: RequireUser,
) -> dict[str, str]:
    return {"user_id": user.user_id}
