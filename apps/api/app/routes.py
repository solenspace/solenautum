from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from svix.webhooks import Webhook, WebhookVerificationError

from app.config import settings
from app.persistence.repository import UserRepository
from app.runner import run_url_mission
from app.security import RequireUser, limiter
from app.sse import emitter

router = APIRouter()
_users = UserRepository()


def _pick_primary_email(data: dict[str, Any]) -> str | None:
    emails = data.get("email_addresses") or []
    if not emails:
        return None
    primary_id = data.get("primary_email_address_id")
    primary = next(
        (e for e in emails if e.get("id") == primary_id),
        emails[0],
    )
    address = primary.get("email_address") if isinstance(primary, dict) else None
    return address if isinstance(address, str) else None


@router.post("/webhooks/clerk", status_code=status.HTTP_204_NO_CONTENT)
async def clerk_webhook(request: Request) -> None:
    """Sync Clerk identity events into the `users` table.

    Authentication is the Svix signature — no Clerk JWT, no per-user rate
    limit. The route trusts only payloads that verify against
    `CLERK_WEBHOOK_SIGNING_SECRET`. Clerk event types we don't handle are
    silently 204'd to avoid bouncing legitimate retries.
    """
    if settings.clerk_webhook_signing_secret is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "webhook signing secret not configured",
        )

    body = await request.body()
    headers = {
        "svix-id": request.headers.get("svix-id", ""),
        "svix-timestamp": request.headers.get("svix-timestamp", ""),
        "svix-signature": request.headers.get("svix-signature", ""),
    }
    try:
        wh = Webhook(settings.clerk_webhook_signing_secret)
        event: dict[str, Any] = wh.verify(body, headers)
    except WebhookVerificationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid signature") from exc

    event_type = event.get("type")
    data = event.get("data") or {}

    if event_type in {"user.created", "user.updated"}:
        user_id = data.get("id")
        if not isinstance(user_id, str):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing user id")
        email = _pick_primary_email(data)
        if email is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "no email on user")
        await _users.upsert(user_id=user_id, email=email)

    elif event_type == "user.deleted":
        user_id = data.get("id")
        if not isinstance(user_id, str):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing user id on deletion")
        await _users.delete(user_id=user_id)


@router.get("/run-mission")
@limiter.limit("60/minute")
async def run_mission(
    request: Request,  # noqa: ARG001 — slowapi keys off the `request` parameter
    user: RequireUser,
    url: str = Query(..., min_length=1, max_length=2048),
    last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Single-task mission entry point. Awaits the mission inline (Spec 07
    single-task missions are sub-second to a few seconds) and then streams the
    SSE projection. Spec 10 separates start from streaming so an N-URL mission
    can begin streaming while later tasks queue.
    """
    mission_id = await run_url_mission(user=user, url=url)

    async def _gen() -> Any:
        async with emitter.stream(mission_id, last_event_id=last_event_id) as iterator:
            async for chunk in iterator:
                yield chunk

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
