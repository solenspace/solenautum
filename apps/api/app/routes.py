from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

import structlog
from clerk_backend_api import Clerk
from fastapi import APIRouter, Header, HTTPException, Path, Request, Response, status
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field, StringConstraints, field_serializer
from svix.webhooks import Webhook, WebhookVerificationError

from app.config import settings
from app.persistence.blob import get_blob_store
from app.persistence.models import Mission, MissionMode, MissionPhase, Status, Task, Tier
from app.persistence.repository import MissionRepository, TaskRepository, UserRepository
from app.runner import (
    start_description_mission,
    start_url_mission,
    submit_approval,
)
from app.runner_helpers import emit_mission_terminal, emit_task_terminal
from app.security import RequireUser, assert_safe_url, limiter
from app.sse import emitter

router = APIRouter()
_log = structlog.get_logger()
_users = UserRepository()


async def _ensure_user_provisioned(user_id: str) -> None:
    """Backfill the Clerk user → `users` table mapping if the webhook
    hasn't fired yet. Runs at most once per user (the existence check
    is a PK lookup); the second-and-later requests for the same user
    short-circuit on the SELECT. Production deployments running a
    reachable Clerk webhook will see this branch only on the first
    POST after a sign-up that races the webhook delivery.
    """
    if await _users.exists(user_id):
        return
    email: str | None = None
    try:
        async with Clerk(bearer_auth=settings.clerk_secret_key) as clerk:
            clerk_user = await clerk.users.get_async(user_id=user_id)
            primary_id = getattr(clerk_user, "primary_email_address_id", None)
            for entry in getattr(clerk_user, "email_addresses", []) or []:
                if getattr(entry, "id", None) == primary_id:
                    email = getattr(entry, "email_address", None)
                    break
            if email is None and getattr(clerk_user, "email_addresses", None):
                email = getattr(clerk_user.email_addresses[0], "email_address", None)
    except Exception as exc:  # pragma: no cover — Clerk transient errors must not block missions
        # The JWT is already verified upstream so we know the user is real;
        # the email is cosmetic on the row. Log the lookup miss and fall
        # through to ensure_provisioned with a placeholder rather than
        # 500 the user request on a transient Clerk-side blip.
        _log.warning("clerk.user_lookup_failed", user_id=user_id, error=str(exc))
    await _users.ensure_provisioned(user_id=user_id, email=email)


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


def _serialize_utc(value: datetime | None) -> str | None:
    """Render a tz-naive UTC datetime with an explicit `Z` suffix.

    Postgres `TIMESTAMP WITHOUT TIME ZONE` rows arrive as naive datetimes
    that the codebase treats as UTC by convention (see
    `_utc_naive_now` in `persistence/models.py`). Pydantic's default
    `model_dump_json` emits naive datetimes without a timezone marker,
    which the browser then parses as *local* time — putting elapsed
    counters and "x seconds ago" relative-time math hours off depending
    on the user's offset. Append `Z` so the wire shape is unambiguously
    UTC and JS `Date.parse` lands on the same instant the api stored.
    """
    if value is None:
        return None
    return value.replace(tzinfo=None).isoformat() + "Z"


class _TaskResponse(BaseModel):
    """JSON projection of a `Task` row for the mission detail endpoint.

    Returned by `GET /missions/{id}` so the slide-over can hydrate task
    lanes from persisted state when the per-mission SSE ring buffer has
    evicted (terminal missions older than the 60s grace). The runner
    keeps emitting live deltas through SSE; the web layer merges them
    on top of this baseline so a 5-minute-old terminal mission renders
    the same lane structure as a freshly-started one.
    """

    id: uuid.UUID
    url: str
    tier_used: Tier
    status: Status
    latency_ms: int | None
    started_at: datetime | None
    finished_at: datetime | None
    snapshot_key: str | None
    parsed_markdown_excerpt: str | None
    summary: str | None

    @field_serializer("started_at", "finished_at")
    def _serialize_timestamps(self, value: datetime | None) -> str | None:
        return _serialize_utc(value)

    @classmethod
    def from_row(cls, row: Task) -> _TaskResponse:
        excerpt = row.parsed_markdown[:500] if row.parsed_markdown is not None else None
        return cls(
            id=row.id,
            url=row.url,
            tier_used=row.tier_used,
            status=row.status,
            latency_ms=row.latency_ms,
            started_at=row.started_at,
            finished_at=row.finished_at,
            snapshot_key=row.snapshot_key,
            parsed_markdown_excerpt=excerpt,
            summary=row.summary,
        )


class _MissionResponse(BaseModel):
    """JSON projection of a `Mission` row for the BFF list / detail endpoints.

    Spec 12 adds `phase`, `skip_approval`, `discovered_urls`, and
    `approved_urls` so the slide-over can re-render the approval gate
    after a refresh. The detail endpoint also populates `tasks` so the
    slide-over can hydrate the lane stack when SSE replay is unavailable.
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
    tasks: list[_TaskResponse] | None = None

    @field_serializer("created_at", "finished_at")
    def _serialize_timestamps(self, value: datetime | None) -> str | None:
        return _serialize_utc(value)

    @classmethod
    def from_row(cls, row: Mission, tasks: list[Task] | None = None) -> _MissionResponse:
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
            tasks=[_TaskResponse.from_row(t) for t in tasks] if tasks is not None else None,
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
    await _ensure_user_provisioned(user.user_id)
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


@router.delete(
    "/missions/{mission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit("60/minute")
async def cancel_mission(
    request: Request,  # noqa: ARG001 — slowapi keys off the `request` parameter
    user: RequireUser,  # noqa: ARG001 — `RequireUser` binds the contextvar
    mission_id: uuid.UUID = Path(...),
) -> Response:
    """Cancel a running mission.

    Routes the cancellation to the live `MissionRunner` if one exists in
    this process; pending tasks settle `CANCELLED` and in-flight tasks
    finish their current network egress (architecture cancellation rule).

    Idempotent: a second DELETE on a terminal mission returns 204 with an
    `x-mission-state` header carrying the current status so the client
    can stop polling. The rare-edge branch (no live runner, but the row
    is still pending/running) writes the row to `CANCELLED` and also
    emits a synthetic mission-level `done(cancelled)` so any client
    attached to the stream within the 60s eviction grace observes the
    terminal event (invariant 5 holds even on the no-runner branch).
    """
    mission = await _missions.get(mission_id)
    if mission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    if mission.status not in {Status.PENDING, Status.RUNNING}:
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={"x-mission-state": mission.status.value},
        )

    runner = emitter.get_active_runner(mission_id)
    if runner is not None and hasattr(runner, "request_cancellation"):
        runner.request_cancellation()
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={"x-mission-state": "cancellation_pending"},
        )

    # Rare edge: row says pending/running but no live runner. Write the
    # row first (invariant 7) then flush a synthetic mission-level
    # terminal so any in-grace listener stops waiting.
    await _missions.update_status(mission_id, Status.CANCELLED)
    await emit_mission_terminal(emitter, mission_id=mission_id, status=Status.CANCELLED)
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"x-mission-state": Status.CANCELLED.value},
    )


@router.delete(
    "/missions/{mission_id}/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit("60/minute")
async def cancel_task(
    request: Request,  # noqa: ARG001 — slowapi keys off the `request` parameter
    user: RequireUser,  # noqa: ARG001 — `RequireUser` binds the contextvar
    mission_id: uuid.UUID = Path(...),
    task_id: uuid.UUID = Path(...),
) -> Response:
    """Cancel a single task within a still-running mission.

    Pending tasks (semaphore-waiting, not yet past `task_start`) exit
    `Status.CANCELLED` immediately at the next per-task cancel checkpoint
    inside `_run_task`. In-flight tasks (already past the agent dispatch)
    finish their current network egress — the architecture cancellation
    rule for tasks mirrors the mission-level rule. Idempotent.
    """
    tasks_repo = TaskRepository()
    task = await tasks_repo.get(task_id)
    if task is None or task.mission_id != mission_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    if task.status not in {Status.PENDING, Status.RUNNING}:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    runner = emitter.get_active_runner(mission_id)
    if runner is not None and hasattr(runner, "cancel_task"):
        runner.cancel_task(task_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # Rare edge: the live runner isn't in this process. Mark the task
    # cancelled (invariant 7) then flush a synthetic `task_end` so any
    # in-grace listener stops waiting on this lane (invariant 5).
    await tasks_repo.update(task_id, status=Status.CANCELLED)
    await emit_task_terminal(
        emitter,
        mission_id=mission_id,
        task_id=task_id,
        status=Status.CANCELLED,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/missions/{mission_id}/tasks/{task_id}/snapshot")
@limiter.limit("60/minute")
async def task_snapshot(
    request: Request,  # noqa: ARG001 — slowapi keys off the `request` parameter
    user: RequireUser,  # noqa: ARG001 — `RequireUser` binds the contextvar
    mission_id: uuid.UUID = Path(...),
    task_id: uuid.UUID = Path(...),
) -> RedirectResponse:
    """Redirect to a 1-hour signed URL for the task's HTML snapshot.

    Ownership is enforced at the application layer (the repository
    lookup is `user_id`-scoped via the contextvar) with RLS as the
    backstop. A missing snapshot returns 404 distinguishably from a
    cross-tenant id (which also returns 404 — see `get_mission`).

    The signed URL is generated fresh per request and never persisted
    anywhere. For the local-fs blob backend (dev), `signed_url` returns
    a `file://` URL that browsers refuse to follow; the web disables
    the download link in dev to avoid a confusing dead-end.
    """
    tasks_repo = TaskRepository()
    task = await tasks_repo.get(task_id)
    if task is None or task.mission_id != mission_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    if task.snapshot_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no snapshot for this task")

    blob = get_blob_store()
    url = await blob.signed_url(task.snapshot_key, expires_in_seconds=3600)
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


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
    """Single mission detail with persisted task list.

    The slide-over hydrates from this when the per-mission SSE ring buffer
    has evicted (terminal missions older than the 60s grace) so the user
    still sees lane status, latency, snapshot link, and a markdown preview
    instead of a stale "Connecting…" placeholder. Live SSE deltas are
    merged on top of this baseline by the web layer.

    RLS hides cross-tenant rows, so a not-owned id returns 404 — same
    shape a non-existent id returns. The application layer does not
    branch on ownership vs. existence to keep enumeration cheap.
    """
    row = await _missions.get(mission_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    tasks = await TaskRepository().list_by_mission(mission_id)
    return _MissionResponse.from_row(row, tasks=tasks)


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
