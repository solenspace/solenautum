from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Path, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StringConstraints
from svix.webhooks import Webhook, WebhookVerificationError

from app.config import settings
from app.persistence.models import Mission, MissionMode, MissionPhase, Status
from app.persistence.repository import MissionRepository, UserRepository
from app.runner import (
    start_description_mission,
    start_url_mission,
    submit_approval,
)
from app.security import RequireUser, assert_safe_url, limiter
from app.sse import emitter

router = APIRouter()
_users = UserRepository()
_missions = MissionRepository()

_MAX_URLS_PER_MISSION = 20


_MissionUrl = Annotated[str, StringConstraints(min_length=1, max_length=2048)]


class _CreateUrlMissionRequest(BaseModel):
    """URL-mode mission body. `mode="url"` is the default so legacy
    clients posting `{"urls": [...]}` continue to parse.
    """

    mode: Literal["url"] = "url"
    urls: list[_MissionUrl] = Field(min_length=1, max_length=_MAX_URLS_PER_MISSION)


class _CreateDescriptionMissionRequest(BaseModel):
    """Description-mode mission body. The discovery agent runs against
    `query`; user approves the resulting URLs via the side-channel
    `/missions/{id}/approve` POST.
    """

    mode: Literal["description"]
    query: str = Field(..., min_length=1, max_length=2000)
    skip_approval: bool = False


_CreateMissionRequest = Annotated[
    _CreateUrlMissionRequest | _CreateDescriptionMissionRequest,
    Field(discriminator="mode"),
]


class ApproveMissionRequest(BaseModel):
    """Approval-gate submit body. `urls` carries the user-edited subset
    of `discovered_urls`; each URL is SSRF-validated before the runner
    is unparked.
    """

    urls: list[_MissionUrl] = Field(min_length=1, max_length=_MAX_URLS_PER_MISSION)
    skip_approval: bool = False


class _MissionResponse(BaseModel):
    """JSON projection of a `Mission` row for the BFF list / detail endpoints.

    Spec 12 adds `phase`, `skip_approval`, `discovered_urls`, and
    `approved_urls` so the slide-over can re-render the approval gate
    after a refresh.
    """

    id: uuid.UUID
    prompt: str
    mode: MissionMode
    status: Status
    cost_cents: int
    created_at: datetime
    finished_at: datetime | None
    phase: MissionPhase | None = None
    skip_approval: bool = False
    discovered_urls: list[dict[str, Any]] | None = None
    approved_urls: list[str] | None = None

    @classmethod
    def from_row(cls, row: Mission) -> _MissionResponse:
        return cls(
            id=row.id,
            prompt=row.prompt,
            mode=row.mode,
            status=row.status,
            cost_cents=row.cost_cents,
            created_at=row.created_at,
            finished_at=row.finished_at,
            phase=row.phase,
            skip_approval=row.skip_approval,
            discovered_urls=row.discovered_urls,
            approved_urls=row.approved_urls,
        )


class _MissionListResponse(BaseModel):
    missions: list[_MissionResponse]


class _StartMissionResponse(BaseModel):
    mission_id: uuid.UUID


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


@router.post("/missions", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
async def post_mission(
    request: Request,  # noqa: ARG001 — slowapi keys off the `request` parameter
    user: RequireUser,
    body: _CreateMissionRequest,
) -> _StartMissionResponse:
    """Start a mission and return immediately with its id.

    Two flavors discriminated on `mode`:
      - `mode="url"` — 1-20 URLs scraped directly (Spec 10).
      - `mode="description"` — Tavily discovery + approval gate +
        scraping (Spec 12).

    The runner is owned by the lifespan-scoped TaskGroup (invariant 3);
    the caller picks up SSE on `/run-mission/{mission_id}/stream`.
    """
    if isinstance(body, _CreateDescriptionMissionRequest):
        mission_id = await start_description_mission(
            user=user, query=body.query, skip_approval=body.skip_approval
        )
    else:
        mission_id = await start_url_mission(user=user, urls=body.urls)
    return _StartMissionResponse(mission_id=mission_id)


@router.post(
    "/missions/{mission_id}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit("60/minute")
async def approve_mission(
    request: Request,  # noqa: ARG001 — slowapi keys off the `request` parameter
    user: RequireUser,  # noqa: ARG001 — `RequireUser` binds the contextvar
    body: ApproveMissionRequest,
    mission_id: uuid.UUID = Path(...),
) -> None:
    """Hand the user-approved URL list to a parked description-mode runner.

    Validates ownership (RLS-scoped lookup), phase (`AWAITING_APPROVAL`),
    and SSRF-safety on every URL before unparking. A 503 surfaces the
    "no in-memory pending approval" case that arises after a process
    restart (Deviation 4 — silent 204 would lie to the client).
    """
    mission = await _missions.get(mission_id)
    if mission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    if mission.phase != MissionPhase.AWAITING_APPROVAL:
        raise HTTPException(status.HTTP_409_CONFLICT, "mission is not awaiting approval")

    for url in body.urls:
        assert_safe_url(url)  # invariant 1 — even on user-edited URLs

    outcome = submit_approval(
        mission_id,
        approved_urls=list(body.urls),
        skip_approval=body.skip_approval,
    )
    if outcome == "no_pending":
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "approval registry has no pending entry; the runner may have "
            "restarted — retry once the mission re-enters awaiting_approval",
        )


@router.get("/missions")
@limiter.limit("60/minute")
async def list_missions(
    request: Request,  # noqa: ARG001 — slowapi keys off the `request` parameter
    user: RequireUser,  # noqa: ARG001 — `RequireUser` binds the contextvar that scopes the repo query
) -> _MissionListResponse:
    """All missions owned by the current user, newest first. Used by the web
    sidebar to group by status.
    """
    rows = await _missions.list_all()
    return _MissionListResponse(missions=[_MissionResponse.from_row(row) for row in rows])


@router.get("/missions/{mission_id}")
@limiter.limit("60/minute")
async def get_mission(
    request: Request,  # noqa: ARG001 — slowapi keys off the `request` parameter
    user: RequireUser,  # noqa: ARG001 — `RequireUser` binds the contextvar that scopes the repo query
    mission_id: uuid.UUID = Path(...),
) -> _MissionResponse:
    """Single mission detail. RLS hides cross-tenant rows, so a not-owned id
    returns 404 — same shape a non-existent id returns. The application layer
    does not branch on ownership vs. existence to keep enumeration cheap.
    """
    row = await _missions.get(mission_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    return _MissionResponse.from_row(row)


@router.get("/run-mission/{mission_id}/stream")
@limiter.limit("60/minute")
async def stream_mission(
    request: Request,  # noqa: ARG001 — slowapi keys off the `request` parameter
    user: RequireUser,  # noqa: ARG001 — `RequireUser` binds the contextvar that scopes the repo query
    mission_id: uuid.UUID = Path(...),
    last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Attach an SSE consumer to a mission already started by `POST /missions`.

    Ownership is verified at the application layer before the stream opens so
    a cross-tenant attempt returns 404 immediately rather than draining the
    rate budget on a hung connection. RLS still back-stops every repo call,
    but the explicit lookup gives a fast-path 404.
    """
    if await _missions.get(mission_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    return _stream_response(mission_id, last_event_id=last_event_id)


def _stream_response(mission_id: uuid.UUID, *, last_event_id: int | None) -> StreamingResponse:
    async def _gen() -> Any:
        async with emitter.stream(mission_id, last_event_id=last_event_id) as iterator:
            async for chunk in iterator:
                yield chunk

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
