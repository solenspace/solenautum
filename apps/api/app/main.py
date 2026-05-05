from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.security import RequireUser, limiter

app = FastAPI(title="Autumn API")
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


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
