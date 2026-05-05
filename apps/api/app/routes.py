from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from svix.webhooks import Webhook, WebhookVerificationError

from app.config import settings
from app.persistence.repository import UserRepository

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
