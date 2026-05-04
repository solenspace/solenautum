# 12 — url-discovery-tavily

## Goal

Add description-mode missions: a user types a free-text query, the
api calls Tavily to find up to 20 relevant URLs, the user reviews
and approves the URL list inside the same slide-over, and the
mission proceeds into Spec 10's TaskGroup-driven scraping phase
without a route change. The `SearchProvider` interface decouples
Tavily so Exa or Brave can swap in via config later. Discovery
state, approval gate, and scraping happen as one continuous SSE
stream with a single side-channel POST for approval.

## Dependencies

- `specs/05` — `MissionRepository`, `MissionMode`, alembic
- `specs/06` — `SseEvent` schema, ring buffer
- `specs/07` — Pydantic AI agent build, `LLMProviderChain`,
  Langfuse tracing
- `specs/09` — three tier tools, `MissionDeps`, `MissionResult`
- `specs/10` — `MissionRunner`, `TaskGroup`, layered semaphores,
  `start_url_mission`
- `specs/11` — `TaskLaneStack`, `MissionDetailSlideover`

## Design Decisions

### Architecture

- **Two agents, two roles, one mission run.**
  - `discovery_agent` (one tool: `discover_urls`) runs first.
    Returns a `DiscoveryResult` listing the URLs Tavily found.
  - `scrape_agent` (three tier tools, unchanged from Spec 09) runs
    once per approved URL inside the TaskGroup, exactly like
    URL-mode missions in Spec 10.
- **One SSE stream end-to-end.** The mission's events flow
  through one `mission_id` queue: `url_discovered`* (per Tavily
  result) → mission-level `discovery_complete` → user POSTs
  approval → `task_start`* + downstream events. Ring buffer
  serves Spec 06's `Last-Event-ID` resume across the whole
  stream.
- **Approval is side-channel REST.** SSE is unidirectional. The
  client POSTs `/missions/{id}/approve` with the approved URL
  list to break the runner's wait. The runner is parked on an
  `asyncio.Event`; the POST sets it and supplies the approved
  list.
- **Discovery continues if the slide-over closes.** Closing the
  slide-over does not cancel discovery. The mission lands in
  `phase=awaiting_approval`; the sidebar surfaces it under a new
  status group. Re-opening the slide-over re-attaches via SSE
  resume and renders the approval gate.
- **`phase` column is new and separate from `status`.**
  - `status` (existing): `pending | running | succeeded | failed
    | cancelled` — lifecycle
  - `phase` (new):
    `discovering | awaiting_approval | scraping | done` — per-
    description-mode workflow position
  - URL-mode missions move from `null → scraping → done`; the
    column carries `null` for them and is informational, not
    behavioral. (We do not nullable-shame the column; URL-mode
    just sets it to `scraping` at start so the dashboard can
    treat all missions uniformly.)
- **`skip_approval` column** lives on the mission row. Per-
  mission scope only; no cross-mission persistence in this spec.
  Used by future re-search calls in the same mission (rare in
  Spec 12 but cheap to honor).
- **`discovered_urls` column** stores the Tavily result list
  (jsonb, immutable once written). Survives process restart so
  the approval gate can re-render after a refresh.

### Tavily integration

- **Single `SearchProvider` Protocol** in `app/llm/search.py` (or
  a new `app/search/`):

  ```python
  class SearchProvider(Protocol):
      name: str
      async def search(self, query: str, *, max_results: int = 20) -> list[DiscoveredUrl]: ...
  ```

- **`TavilyProvider`** is the only implementation in this spec.
  Hits `https://api.tavily.com/search` with `search_depth="basic"`,
  `include_answer=False`, `max_results=20`. Returns a list of
  `DiscoveredUrl(url, score, source, favicon_url=None,
  title=None)`.
- **Per-mission cost cap** is enforced at three layers:
  1. The agent's system prompt constrains it to call
     `discover_urls` exactly once.
  2. The tool wrapper rejects a second call within the same
     mission run (in-memory mission-scoped flag).
  3. The Tavily API call sets `max_results=20` so a runaway
     prompt cannot ask for 100.
- **Provider switching is config-only.** No fallback chain in this
  spec — Tavily fails closed and the mission terminates with an
  error event (`discovery_failed`). Exa and Brave swap in later by
  changing one env var and one provider class binding; the
  `SearchProvider` Protocol is the seam.

### Discovery tool result and SSE events

- `discover_urls` tool returns:

  ```python
  class DiscoveredUrl(BaseModel):
      url: str
      score: float = Field(..., ge=0.0, le=1.0)
      source: str  # "tavily"
      favicon_url: str | None = None
      title: str | None = None


  class DiscoveryResult(BaseModel):
      urls: list[DiscoveredUrl]
  ```

- During the tool's body, before returning, emit one
  `url_discovered` SSE event per result — the schema already
  supports it (Spec 06). Then the tool returns. The runner emits
  a mission-level `discovery_complete` event next.
- **Schema addition: `discovery_complete` event** added to
  `packages/sse-protocol/schema.json`. Triggers regeneration of
  TS + pydantic models. Shape:

  ```json
  {
    "type": "discovery_complete",
    "content": {
      "count": <int>,
      "awaiting_approval": <bool>
    },
    "mission_id": "<uuid>",
    "seq": <int>
  }
  ```

  `awaiting_approval` is `false` only when `skip_approval` is
  set — in that case the runner proceeds straight to scraping.

### Approval gate (web — research-driven)

Density patterns from the Devin / Manus / Linear / Notion research
are non-negotiable. Concrete rules for the gate component:

- **Inline in the slide-over**, between the `AggregateHeader` and
  the (eventual) `TaskLaneStack`. State machine renders one stage
  at a time, with prior stages collapsed into a one-line summary
  row at the top.
- **Row shape, 28px**:
  `[checkbox] [favicon-12px] [domain-mono] [path-mono-truncated] [score-pill] [edit-on-hover]`
- **Default state**: all URLs checked **except** those with
  `score < 0.4`, which ship unchecked and dimmed
  (`text-muted-foreground/60`). The agent's own confidence drives
  the default; users can flip individually or hit `⌘A` to toggle
  all.
- **Sort**: default `score desc`, secondary `domain asc`. Header
  row provides a single "sort by score / sort by domain" toggle
  (no full table-header row at this density).
- **Domain filter chip strip** above the list — `flex flex-wrap
  gap-1` of chips (`example.com (8)` `acme.io (3)` …). Click a
  chip → filters the list. `data-[active=true]` highlights the
  active filter. `Esc` clears.
- **Inline edit**: clicking the URL text (path or domain) puts the
  whole row's URL into a text input that matches the row height.
  Enter commits, Esc cancels, blur commits. Validation: must be
  a valid URL; invalid shows a red underline + tooltip; does not
  block other rows. Edited URLs get a small `text-[11px]
  text-muted-foreground` "edited" tag at row-end.
- **Sticky bottom toolbar** inside the slide-over (not the
  viewport):

  ```
  [N selected of 20] · [Approve N URLs (⌘↩)] · [Edit selection] · [Deselect all]
  ```

  No "Reject all" button — rejection is "deselect all + close
  slide-over" (which lands the mission in `awaiting_approval`
  permanently until reaper times it out per Spec 14). Avoiding
  the destructive button keeps the surface low-stakes.
- **Score pill**: `inline-flex h-5 px-1.5 items-center gap-1
  rounded text-[11px] font-mono tabular-nums` with leading dot
  colored by band:
  - `≥ 0.8` → `bg-state-success`
  - `0.5–0.8` → `bg-state-warn`
  - `< 0.5` → `bg-text-muted/40`
- **Streaming counter** during discovery:
  `Searching… {n} found` chip in the same row as the toolbar's
  count, with a pulsing leading dot. Approve button is **disabled
  during discovery**; enables on `discovery_complete`.
- **Auto-approve toggle** (single checkbox under the toolbar):
  `Skip approval for this mission's future searches`. Persists
  via the api `PATCH /missions/{id}` endpoint to set
  `missions.skip_approval = true`. No global setting.
- **Error states**:
  - 0 URLs: `No results for this query.` + `Refine query`
    text-button → returns to the description-mode form prefilled.
  - Vague query (api-side detection: low aggregate score,
    `< 0.3` average): banner above the list — `Query needs more
    specificity. Try adding a domain, timeframe, or a concrete
    entity.` — list still rendered with whatever Tavily returned.
  - Tavily rate limit / 5xx: `Search paused — Tavily returned
    {status}.` with `Retry` text-button. No silent auto-retry.

### Mobile (< 768px)

- Approval gate uses the same 28px rows but hides the path
  segment (domain + favicon + checkbox + score only). Tapping the
  row expands a single-row peek showing the full URL with edit
  affordance.
- Sticky toolbar moves to a bottom sheet for thumb reach.
- Domain filter chip strip is horizontally scrollable.

### Description-mode form

- **Cmd+K** gets a third item: `New description-mode mission`,
  shortcut `⌘⇧D` (density-friendly variant of `⌘⇧N`).
- The form is a slide-over (mirror of multi-URL slide-over from
  Spec 10): single `<textarea>` for the query, max 2000 chars,
  validated client-side. Submit via `⌘↩`. The slide-over closes
  on submit; the mission detail slide-over opens with the
  discovery state.
- The persistent top-bar URL input remains URL-mode-only. Mode
  selection is per-input-surface, not a top-bar toggle.

References:
- `context/architecture.md` — Search section, **Invariants 1, 4,
  7, 10** (discovery still must run inside the mission lifecycle)
- `context/code-standards.md` — Python (pydantic v2), TypeScript,
  i18n
- `context/ui-context.md` — Voice & Copy, density patterns
- Skills: `pydantic-ai-dependency-injection`, `fastapi`,
  `next-best-practices`, `vercel-composition-patterns`

## Implementation

### A. Install + env

```bash
cd apps/api
uv add tavily-python
```

`apps/api/.env.example` — append:

```
TAVILY_API_KEY=tvly-...
```

`apps/api/app/config.py` — add field:

```python
tavily_api_key: str = Field(..., alias="TAVILY_API_KEY")
```

### B. SearchProvider Protocol — `apps/api/app/search/__init__.py`

```python
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class DiscoveredUrl(BaseModel):
    url: str
    score: float = Field(..., ge=0.0, le=1.0)
    source: str
    favicon_url: str | None = None
    title: str | None = None


class SearchProvider(Protocol):
    name: str

    async def search(
        self, query: str, *, max_results: int = 20
    ) -> list[DiscoveredUrl]: ...
```

### C. TavilyProvider — `apps/api/app/search/tavily.py`

```python
from __future__ import annotations

import httpx
from pydantic import BaseModel

from app.config import settings
from app.search import DiscoveredUrl


class _TavilyResult(BaseModel):
    url: str
    title: str | None = None
    score: float
    raw_favicon: str | None = None


class TavilyProvider:
    name = "tavily"

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def search(
        self, query: str, *, max_results: int = 20
    ) -> list[DiscoveredUrl]:
        owned_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "max_results": min(max_results, 20),
                    "search_depth": "basic",
                    "include_answer": False,
                    "include_raw_content": False,
                },
            )
            response.raise_for_status()
            data = response.json()
        finally:
            if owned_client:
                await client.aclose()

        results = [_TavilyResult.model_validate(r) for r in data.get("results", [])]
        return [
            DiscoveredUrl(
                url=r.url,
                score=r.score,
                source="tavily",
                favicon_url=r.raw_favicon,
                title=r.title,
            )
            for r in results
        ]
```

### D. `discover_urls` tool — `apps/api/app/tools/discover.py`

```python
from __future__ import annotations

import contextvars
from typing import Literal
from uuid import UUID

from autumn_sse_protocol import SseEvent
from pydantic import BaseModel, Field

from app.observability import observe
from app.search import DiscoveredUrl
from app.search.tavily import TavilyProvider
from app.sse import emitter


class DiscoverArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    max_results: int = Field(default=20, ge=1, le=20)


class DiscoveryOk(BaseModel):
    status: Literal["ok"] = "ok"
    urls: list[DiscoveredUrl]


class DiscoveryFailure(BaseModel):
    status: Literal["failed"] = "failed"
    reason: Literal["rate_limited", "upstream_error", "no_results"]
    detail: str | None = None


DiscoveryResult = DiscoveryOk | DiscoveryFailure


class DiscoverDeps(BaseModel):
    user_id: str
    mission_id: UUID


_discovery_called: contextvars.ContextVar[set[UUID]] = contextvars.ContextVar(
    "discovery_called", default=set()
)


@observe(name="tool.discover_urls")
async def discover_urls(deps: DiscoverDeps, args: DiscoverArgs) -> DiscoveryResult:
    """Tavily-backed search. Per-mission single-call cap is enforced
    in-process; the agent's system prompt also constrains it."""
    called = _discovery_called.get()
    if deps.mission_id in called:
        return DiscoveryFailure(
            reason="upstream_error",
            detail="discovery already called this mission",
        )
    _discovery_called.set(called | {deps.mission_id})

    provider = TavilyProvider()
    try:
        urls = await provider.search(args.query, max_results=args.max_results)
    except Exception as exc:
        return DiscoveryFailure(reason="upstream_error", detail=str(exc))

    if not urls:
        return DiscoveryFailure(reason="no_results")

    # Emit per-URL events as we have them.
    for u in urls:
        await emitter.emit(
            SseEvent.model_validate(
                {
                    "type": "url_discovered",
                    "content": {
                        "url": u.url,
                        "source": u.source,
                        "score": u.score,
                    },
                    "mission_id": str(deps.mission_id),
                    "seq": 0,  # emitter assigns
                }
            )
        )

    return DiscoveryOk(urls=urls)
```

### E. Discovery agent — extend `apps/api/app/agent.py`

```python
class DiscoveryDeps(BaseModel):
    user_id: str
    mission_id: UUID


class DiscoveryMissionResult(BaseModel):
    """The discovery agent's output. Successful discovery returns the URLs;
    failure returns an error code."""
    status: Literal["ok", "error"]
    urls: list[DiscoveredUrl] = []
    error_code: Literal["discovery_failed", "no_results", "rate_limited"] | None = None
    error_message: str | None = None


_DISCOVERY_SYSTEM_PROMPT = """
You are Autumn's URL-discovery agent. The user gives you a free-text
description; you call `discover_urls` once with that query, then
return the resulting URL list as a DiscoveryMissionResult.

Rules:
- Call `discover_urls` exactly once. Never twice.
- If the tool returns reason=no_results, return DiscoveryMissionResult
  with status='error', error_code='no_results'.
- If the tool returns reason=upstream_error or rate_limited, return
  DiscoveryMissionResult with status='error' and the matching error_code.
- On success, return status='ok' and the urls list.

Do not transform the URLs. Do not filter by score. The user reviews them.
""".strip()


def build_discovery_agent(model_factory) -> Agent[DiscoveryDeps, DiscoveryMissionResult]:
    agent = Agent[DiscoveryDeps, DiscoveryMissionResult](
        model=model_factory,
        deps_type=DiscoveryDeps,
        output_type=DiscoveryMissionResult,
        system_prompt=_DISCOVERY_SYSTEM_PROMPT,
        retries=2,
    )

    @agent.tool
    async def discover(ctx: RunContext[DiscoveryDeps], query: str) -> DiscoveryResult:
        """Run the search provider for the given query."""
        return await discover_urls_impl(
            DiscoverDeps(user_id=ctx.deps.user_id, mission_id=ctx.deps.mission_id),
            DiscoverArgs(query=query, max_results=20),
        )

    return agent
```

The Spec 09 `build_agent` (now `build_scrape_agent` for clarity)
keeps its three-tool registration. Both agents share the
`LLMProviderChain`.

### F. Migration — alembic revision

```
0002_add_mission_phase_and_skip_approval
```

```python
def upgrade() -> None:
    op.add_column(
        "missions",
        sa.Column("phase", sa.Enum(
            "discovering", "awaiting_approval", "scraping", "done",
            name="mission_phase",
        ), nullable=True),
    )
    op.add_column("missions", sa.Column("skip_approval", sa.Boolean, nullable=False, server_default=sa.text("false")))
    op.add_column(
        "missions",
        sa.Column("discovered_urls", postgresql.JSONB, nullable=True),
    )
    op.add_column(
        "missions",
        sa.Column("approved_urls", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("missions", "approved_urls")
    op.drop_column("missions", "discovered_urls")
    op.drop_column("missions", "skip_approval")
    op.drop_column("missions", "phase")
    op.execute("DROP TYPE IF EXISTS mission_phase")
```

The `Mission` sqlmodel adds the four fields:

```python
phase: MissionPhase | None = Field(default=None)
skip_approval: bool = Field(default=False)
discovered_urls: list[dict] | None = Field(default=None, sa_column=Column(JSONB))
approved_urls: list[str] | None = Field(default=None, sa_column=Column(JSONB))
```

### G. Approval mechanism — `apps/api/app/runner.py`

Add a per-process registry of `asyncio.Event`s keyed on
`mission_id`. The `MissionRunner` for description-mode parks on
the event after discovery; the `/approve` endpoint sets it.

```python
# in runner.py

_pending_approvals: dict[UUID, "ApprovalRequest"] = {}


@dataclass(slots=True)
class ApprovalRequest:
    event: asyncio.Event
    approved_urls: list[str] | None = None
    skip_approval_persisted: bool = False


def register_pending_approval(mission_id: UUID) -> ApprovalRequest:
    req = ApprovalRequest(event=asyncio.Event())
    _pending_approvals[mission_id] = req
    return req


def submit_approval(
    mission_id: UUID, *, approved_urls: list[str], skip_approval: bool
) -> None:
    req = _pending_approvals.get(mission_id)
    if req is None:
        return  # mission already advanced or never paused
    req.approved_urls = approved_urls
    req.skip_approval_persisted = skip_approval
    req.event.set()


async def wait_for_approval(
    mission_id: UUID, *, timeout_s: float = 1800
) -> ApprovalRequest | None:
    req = _pending_approvals.get(mission_id)
    if req is None:
        return None
    try:
        await asyncio.wait_for(req.event.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        return None
    finally:
        _pending_approvals.pop(mission_id, None)
    return req
```

The `MissionRunner` gets a description-mode entry path:

```python
async def run_description_mission(
    *,
    user: CurrentUser,
    mission: Mission,
    query: str,
) -> None:
    _current_user.set(user)
    missions = MissionRepository()
    await missions.set_phase(mission.id, MissionPhase.DISCOVERING)

    chain = LLMProviderChain(primary=OpenRouterProvider(), fallback=GroqProvider())

    async def _run(model):
        agent = build_discovery_agent(model_factory=lambda: model)
        return await agent.run(query, deps=DiscoveryDeps(
            user_id=user.user_id, mission_id=mission.id,
        ))

    try:
        result = await chain.with_fallback(_run)
    except Exception as exc:
        await missions.update_status(mission.id, Status.FAILED)
        await emitter.emit(
            SseEvent.model_validate({
                "type": "error",
                "content": {"code": "discovery_failed", "message": str(exc)},
                "mission_id": str(mission.id),
                "seq": 0,
            })
        )
        await emitter.emit(SseEvent.model_validate({
            "type": "done",
            "content": {"mission_status": "failed", "cost_cents": 0},
            "mission_id": str(mission.id),
            "seq": 0,
        }))
        return

    discovery: DiscoveryMissionResult = result.output
    if discovery.status == "error":
        await missions.update_status(mission.id, Status.FAILED)
        await emitter.emit(SseEvent.model_validate({
            "type": "error",
            "content": {
                "code": discovery.error_code or "discovery_failed",
                "message": discovery.error_message or "discovery failed",
            },
            "mission_id": str(mission.id),
            "seq": 0,
        }))
        await emitter.emit(SseEvent.model_validate({
            "type": "done",
            "content": {"mission_status": "failed", "cost_cents": 0},
            "mission_id": str(mission.id),
            "seq": 0,
        }))
        return

    # Persist discovered URLs and emit discovery_complete.
    await missions.set_discovered_urls(mission.id, [u.model_dump() for u in discovery.urls])

    fresh_mission = await missions.get(mission.id)
    awaiting = not (fresh_mission and fresh_mission.skip_approval)

    if awaiting:
        await missions.set_phase(mission.id, MissionPhase.AWAITING_APPROVAL)
    await emitter.emit(SseEvent.model_validate({
        "type": "discovery_complete",
        "content": {"count": len(discovery.urls), "awaiting_approval": awaiting},
        "mission_id": str(mission.id),
        "seq": 0,
    }))

    if awaiting:
        approval_req = register_pending_approval(mission.id)
        approval = await wait_for_approval(mission.id, timeout_s=1800)
        if approval is None or approval.approved_urls is None:
            await missions.update_status(mission.id, Status.CANCELLED)
            await emitter.emit(SseEvent.model_validate({
                "type": "done",
                "content": {"mission_status": "cancelled", "cost_cents": 0},
                "mission_id": str(mission.id),
                "seq": 0,
            }))
            return
        approved_urls = approval.approved_urls
        if approval.skip_approval_persisted:
            await missions.set_skip_approval(mission.id, True)
        await missions.set_approved_urls(mission.id, approved_urls)
    else:
        # skip_approval was set on the mission row beforehand
        approved_urls = [u.url for u in discovery.urls]
        await missions.set_approved_urls(mission.id, approved_urls)

    # Now run the URL-mode TaskGroup runner with the approved URLs.
    await missions.set_phase(mission.id, MissionPhase.SCRAPING)
    tasks_repo = TaskRepository()
    task_rows = []
    for url in approved_urls:
        t = await tasks_repo.create(
            mission_id=mission.id, url=url, tier_used=Tier.HTTP
        )
        task_rows.append(t)

    runner = MissionRunner(user=user, mission=fresh_mission, tasks=task_rows)
    await runner.run()
    await missions.set_phase(mission.id, MissionPhase.DONE)
```

The 30-minute approval timeout is hard-coded in the spec; if no
approval arrives, the mission is `cancelled`. Spec 14 may revisit
with a configurable timeout and a reaper-driven cleanup.

### H. POST /missions polymorphic — `apps/api/app/routes.py`

```python
from typing import Literal


class CreateUrlMissionRequest(BaseModel):
    mode: Literal["url"]
    urls: conlist(str, min_length=1, max_length=20)


class CreateDescriptionMissionRequest(BaseModel):
    mode: Literal["description"]
    query: str = Field(..., min_length=1, max_length=2000)
    skip_approval: bool = False


CreateMissionRequest = CreateUrlMissionRequest | CreateDescriptionMissionRequest


@router.post("/missions", status_code=202)
async def create_mission(
    request: CreateMissionRequest,
    user: RequireUser,
) -> dict[str, str]:
    if request.mode == "url":
        mission_id = await start_url_mission(user=user, urls=request.urls)
    else:
        mission_id = await start_description_mission(
            user=user, query=request.query, skip_approval=request.skip_approval
        )
    return {"mission_id": str(mission_id)}
```

`start_description_mission` creates the mission row with
`mode=DESCRIPTION` and `skip_approval=request.skip_approval`,
adopts a runner via the emitter's lifespan TaskGroup (Spec 10
pattern), returns the id immediately.

### I. Approval endpoint — `apps/api/app/routes.py`

```python
class ApprovalRequest(BaseModel):
    urls: conlist(str, min_length=1, max_length=20)
    skip_approval: bool = False


@router.post("/missions/{mission_id}/approve", status_code=204)
async def approve(
    mission_id: UUID,
    request: ApprovalRequest,
    user: RequireUser,
) -> None:
    # Validate ownership via repository (RLS backstop is defence-in-depth).
    missions = MissionRepository()
    mission = await missions.get(mission_id)
    if mission is None:
        raise HTTPException(404, "not found")
    if mission.phase != MissionPhase.AWAITING_APPROVAL:
        raise HTTPException(409, "mission is not awaiting approval")

    # SSRF + URL validation on each approved URL before parking the runner.
    for url in request.urls:
        assert_safe_url(url)

    submit_approval(
        mission_id,
        approved_urls=request.urls,
        skip_approval=request.skip_approval,
    )
```

### J. Schema regen — `packages/sse-protocol/schema.json`

Add `DiscoveryComplete` to the `oneOf` and `$defs`:

```json
"DiscoveryComplete": {
  "allOf": [
    { "$ref": "#/$defs/BaseEvent" },
    {
      "type": "object",
      "properties": {
        "type": { "const": "discovery_complete" },
        "content": {
          "type": "object",
          "required": ["count", "awaiting_approval"],
          "properties": {
            "count": { "type": "integer", "minimum": 0 },
            "awaiting_approval": { "type": "boolean" }
          }
        }
      }
    }
  ]
}
```

Run `pnpm --filter @autumn/sse-protocol generate` to regenerate
TS + pydantic models. Round-trip test in
`packages/sse-protocol/tests/round-trip.test.ts` adds a case for
`discovery_complete`.

### K. Web — Cmd+K item + description-mode form

`apps/web/widgets/description-mode-slideover/index.tsx` mirrors
the multi-URL slide-over from Spec 10 but with one textarea
(`min-h-32`) and a `skip_approval` checkbox at the bottom. Submit
via `⌘↩` calls `submitDescription(query, skipApproval)`.

`apps/web/features/run-mission/use-submit-mission.ts` — add:

```tsx
async function submitDescription(query: string, skipApproval: boolean) {
  setSubmitting(true);
  try {
    const response = await fetch("/api/missions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "description", query, skip_approval: skipApproval }),
    });
    if (!response.ok) {
      setError("missionFailed");
      return;
    }
    const { missionId } = (await response.json()) as { missionId: string };
    open(missionId);
  } finally {
    setSubmitting(false);
  }
}
```

`apps/web/widgets/command-palette/index.tsx` — add:

```tsx
<CommandItem onSelect={() => setDescriptionOpen(true)}>
  <Search className="h-3.5 w-3.5" />
  {t("mission", "newDescriptionMission")}
  <CommandShortcut>⌘⇧D</CommandShortcut>
</CommandItem>
```

### L. Web — approval gate component

`apps/web/widgets/approval-gate/index.tsx`:

```tsx
"use client";

import { useMemo, useState } from "react";

import { useT } from "@/shared/i18n";
import { useApprovalState } from "@/features/run-mission";
import type { DiscoveredUrl } from "@/entities/mission";

import { UrlRow } from "./url-row";
import { DomainFilterStrip } from "./domain-filter-strip";
import { BulkToolbar } from "./bulk-toolbar";


export function ApprovalGate({
  missionId,
  discoveredUrls,
  isStreaming,
}: {
  missionId: string;
  discoveredUrls: DiscoveredUrl[];
  isStreaming: boolean;
}) {
  const t = useT();
  const {
    selected,
    edits,
    domainFilter,
    sortBy,
    toggle,
    toggleAll,
    setEdit,
    setDomainFilter,
    setSortBy,
    submit,
    submitting,
    skipApproval,
    setSkipApproval,
  } = useApprovalState(missionId, discoveredUrls);

  const visible = useMemo(() => filterAndSort(discoveredUrls, edits, domainFilter, sortBy), [discoveredUrls, edits, domainFilter, sortBy]);

  return (
    <div className="flex flex-col">
      <DomainFilterStrip urls={discoveredUrls} active={domainFilter} onChange={setDomainFilter} />
      <ul className="flex flex-col">
        {visible.map((u) => (
          <UrlRow
            key={u.url}
            url={u}
            checked={selected.has(u.url)}
            edited={edits[u.url]}
            onToggle={() => toggle(u.url)}
            onEdit={(v) => setEdit(u.url, v)}
          />
        ))}
      </ul>
      <BulkToolbar
        selectedCount={selected.size}
        totalCount={discoveredUrls.length}
        canSubmit={!isStreaming && selected.size > 0}
        skipApproval={skipApproval}
        onSkipApprovalChange={setSkipApproval}
        onSubmit={submit}
        onToggleAll={toggleAll}
        submitting={submitting}
      />
    </div>
  );
}
```

#### `UrlRow` — 28px row

```tsx
"use client";

import { useState } from "react";
import { z } from "zod";

import type { DiscoveredUrl } from "@/entities/mission";


const urlSchema = z.string().url();


export function UrlRow({
  url,
  checked,
  edited,
  onToggle,
  onEdit,
}: {
  url: DiscoveredUrl;
  checked: boolean;
  edited?: string;
  onToggle: () => void;
  onEdit: (v: string | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const display = edited ?? url.url;
  const parsed = new URL(display);
  const dimmed = url.score < 0.4;

  return (
    <li
      data-state={checked ? "checked" : "unchecked"}
      className="grid h-7 grid-cols-[16px_16px_auto_1fr_auto_24px] items-center gap-2 border-b border-border/50 px-3 hover:bg-muted/40 data-[state=checked]:bg-muted/20"
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="h-3.5 w-3.5 rounded border-border/50"
      />
      {url.favicon_url ? (
        <img src={url.favicon_url} alt="" className="h-3 w-3 rounded-sm" />
      ) : (
        <span className="h-3 w-3" aria-hidden />
      )}
      {editing ? (
        <input
          autoFocus
          type="url"
          defaultValue={display}
          onBlur={(e) => {
            setEditing(false);
            const v = e.currentTarget.value;
            const isValid = urlSchema.safeParse(v).success;
            if (isValid && v !== url.url) onEdit(v);
            else if (v === url.url) onEdit(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            if (e.key === "Escape") {
              (e.target as HTMLInputElement).value = display;
              setEditing(false);
            }
          }}
          className="col-span-3 bg-transparent font-mono text-[13px] outline-hidden"
        />
      ) : (
        <>
          <span
            onClick={() => setEditing(true)}
            className={[
              "font-mono text-[13px]",
              dimmed ? "text-muted-foreground/60" : "text-foreground",
            ].join(" ")}
          >
            {parsed.hostname}
          </span>
          <span
            onClick={() => setEditing(true)}
            className="truncate font-mono text-[13px] text-muted-foreground"
          >
            {parsed.pathname + parsed.search}
          </span>
        </>
      )}
      <ScorePill score={url.score} />
      <span className="text-[11px] text-muted-foreground">
        {edited ? "edited" : null}
      </span>
    </li>
  );
}


function ScorePill({ score }: { score: number }) {
  const band =
    score >= 0.8 ? "bg-state-success" :
    score >= 0.5 ? "bg-state-warn" :
    "bg-text-muted/40";
  return (
    <span className="inline-flex h-5 items-center gap-1 rounded px-1.5 text-[11px] font-mono tabular-nums">
      <span className={`h-1.5 w-1.5 rounded-full ${band}`} aria-hidden />
      {score.toFixed(2)}
    </span>
  );
}
```

#### `BulkToolbar`

```tsx
"use client";

import { useT } from "@/shared/i18n";
import { Kbd } from "@/components/ui/kbd";


export function BulkToolbar({
  selectedCount,
  totalCount,
  canSubmit,
  skipApproval,
  onSkipApprovalChange,
  onSubmit,
  onToggleAll,
  submitting,
}: {
  selectedCount: number;
  totalCount: number;
  canSubmit: boolean;
  skipApproval: boolean;
  onSkipApprovalChange: (v: boolean) => void;
  onSubmit: () => void;
  onToggleAll: () => void;
  submitting: boolean;
}) {
  const t = useT();
  return (
    <div className="sticky bottom-0 flex h-12 items-center gap-3 border-t border-border/50 bg-background/95 px-4 backdrop-blur">
      <span className="text-[11px] font-mono text-muted-foreground tabular-nums">
        {t("mission", "selectedOf", { selected: selectedCount, total: totalCount })}
      </span>
      <span className="flex-1" />
      <button
        type="button"
        onClick={onToggleAll}
        className="text-[11px] text-muted-foreground hover:text-foreground"
      >
        {selectedCount === totalCount ? t("common", "deselectAll") : t("common", "selectAll")}
      </button>
      <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <input
          type="checkbox"
          checked={skipApproval}
          onChange={(e) => onSkipApprovalChange(e.currentTarget.checked)}
        />
        {t("mission", "skipApprovalForFutureSearches")}
      </label>
      <button
        type="button"
        disabled={!canSubmit || submitting}
        onClick={onSubmit}
        className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-[13px] font-medium text-primary-foreground disabled:opacity-50"
      >
        {t("mission", "approveNUrls", { count: selectedCount })}
        <Kbd>⌘↩</Kbd>
      </button>
    </div>
  );
}
```

#### `useApprovalState`

`apps/web/features/run-mission/use-approval-state.ts` owns the
selected set, edits map, sort order, domain filter, submitting
state. On `submit`, calls
`POST /api/missions/{id}/approve { urls, skip_approval }`.

### M. Web — slide-over state machine

The mission slide-over now renders one of four child blocks based
on the mission's phase (derived from the SSE event stream):

```tsx
function SlideOverContent({ missionId }: { missionId: string }) {
  const stream = useMissionStream(missionId);
  const phase = useMissionPhase(missionId, stream.events);
  const discoveredUrls = useDiscoveredUrls(stream.events);

  if (phase === "discovering") {
    return (
      <div className="flex flex-col gap-3 p-4">
        <DiscoveryHeader count={discoveredUrls.length} />
        <DiscoveredList urls={discoveredUrls} streaming />
      </div>
    );
  }
  if (phase === "awaiting_approval") {
    return <ApprovalGate missionId={missionId} discoveredUrls={discoveredUrls} isStreaming={false} />;
  }
  if (phase === "scraping" || phase === "done") {
    return <TaskLaneStack missionId={missionId} />;
  }
  return <ConnectingState />;
}
```

`useMissionPhase` derives from events: receiving any
`url_discovered` → `discovering`; receiving `discovery_complete`
with `awaiting_approval=true` → `awaiting_approval`; receiving
the first `task_start` → `scraping`; receiving `done` → `done`.

For URL-mode missions, `useMissionPhase` skips straight to
`scraping` when the first `task_start` arrives, with no discovery
or approval phase visible.

### N. i18n keys (additions)

- `mission.newDescriptionMission` — "New description-mode mission"
- `mission.descriptionPlaceholder` — "Describe what you need..."
- `mission.searching` — "Searching... {count} found"
- `mission.discoveryComplete` — "{count} URLs found"
- `mission.approveNUrls` — "Approve {count} URLs" (plural via
  `count`)
- `mission.selectedOf` — "{selected} of {total}"
- `mission.skipApprovalForFutureSearches` — "Skip approval for
  this mission's future searches"
- `mission.refineQuery` — "Refine query"
- `mission.querySpecificity` — "Query needs more specificity. Try
  adding a domain, timeframe, or a concrete entity."
- `mission.searchPaused` — "Search paused — Tavily returned {status}."
- `mission.noResults` — "No results for this query."
- `common.deselectAll` — "Deselect all"
- `common.selectAll` — "Select all"
- `validation.queryRequired` — "Query required"
- `validation.queryTooLong` — "Query too long"

### O. Tests

- `apps/api/tests/test_tavily_provider.py` — happy path with
  mocked httpx; rate-limited path raises and surfaces; 0-results
  returns empty list.
- `apps/api/tests/test_discover_tool.py` — second call with same
  mission_id returns `DiscoveryFailure`; `_discovery_called`
  cleared after mission ends; `url_discovered` events emitted.
- `apps/api/tests/test_description_runner.py` — full description-
  mode flow with mocked LLM + mocked Tavily: emits
  `url_discovered` × 5, `discovery_complete`, parks; injecting
  approval triggers scrape phase; mission ends with `done`.
- `apps/api/tests/test_approval_endpoint.py` — auth required;
  ownership check via RLS-aware repository; approval before
  discovery completes returns 409; approval timeout cancels
  mission.
- `apps/web/widgets/approval-gate/url-row.test.tsx` — checkbox
  toggle, inline edit commit/cancel, score pill bands, dimmed
  row at score < 0.4.
- `apps/web/widgets/approval-gate/bulk-toolbar.test.tsx` —
  approve disabled at 0 selected; counts update; skip-approval
  toggle persists.
- `apps/web/features/run-mission/use-approval-state.test.ts` —
  submit sends correct payload; toggles work; sort persists.
- `packages/sse-protocol/tests/round-trip.test.ts` — new
  `discovery_complete` case validates.

### P. Order of operations

1. `cd apps/api && uv add tavily-python`. Add env var.
2. Write `app/search/__init__.py` and `app/search/tavily.py`.
3. Write `app/tools/discover.py`.
4. Extend `app/agent.py` with `build_discovery_agent` +
   `DiscoveryMissionResult`.
5. Generate alembic migration `0002_*`. Add the 4 columns.
   Run `uv run alembic upgrade head` against the dev branch.
6. Update `app/persistence/models.py` with the new fields and
   `MissionPhase` enum. Add repository methods:
   `set_phase`, `set_discovered_urls`, `set_approved_urls`,
   `set_skip_approval`.
7. Implement `register_pending_approval`, `submit_approval`,
   `wait_for_approval` in `app/runner.py`.
8. Implement `start_description_mission` and
   `run_description_mission`.
9. Update `app/routes.py` with the polymorphic
   `CreateMissionRequest` and the `/missions/{id}/approve`
   endpoint.
10. Update `packages/sse-protocol/schema.json` with
    `DiscoveryComplete`. Regenerate.
11. Build the web `description-mode-slideover` and the Cmd+K
    item.
12. Build the `approval-gate` component tree and
    `useApprovalState`.
13. Wire `SlideOverContent` state machine into
    `MissionDetailSlideover`.
14. Add the 14 i18n keys.
15. Run the verification block.

## Out of Scope

- **Exa / Brave provider implementations** — the
  `SearchProvider` Protocol exists; future specs (or an op-time
  decision) bind a different provider via env. No new providers
  in this spec.
- **Cross-mission auto-approve persistence** (Clerk metadata) —
  per-mission only, per the user's choice.
- **Per-search-confidence auto-approval (auto-approve URLs with
  score > 0.8)** — out of scope; the agent's default-checked
  behavior already biases toward "the agent picked these".
- **Reaper for missions parked in `awaiting_approval` longer than
  30 minutes** — Spec 14.
- **Sidebar "Awaiting approval" status group** — Spec 14 (the
  sidebar's grouping logic gets the new phase). Spec 12 ships
  the column; Spec 14 surfaces it in the sidebar UI.
- **Mission-level cancellation through the slide-over close** —
  closing the slide-over does NOT cancel; mission stays parked.
  Spec 14 ships the cancel UI.
- **Discovery-result post-processing (de-duplication, language
  filter, recency boost)** — Tavily owns the relevance ranking;
  we pass results through unmodified.

## Files

### Create

- `apps/api/app/search/__init__.py`
- `apps/api/app/search/tavily.py`
- `apps/api/app/tools/discover.py`
- `apps/api/alembic/versions/0002_*.py`
- `apps/api/tests/test_tavily_provider.py`
- `apps/api/tests/test_discover_tool.py`
- `apps/api/tests/test_description_runner.py`
- `apps/api/tests/test_approval_endpoint.py`
- `apps/web/widgets/description-mode-slideover/index.tsx`
- `apps/web/widgets/approval-gate/index.tsx`
- `apps/web/widgets/approval-gate/url-row.tsx`
- `apps/web/widgets/approval-gate/bulk-toolbar.tsx`
- `apps/web/widgets/approval-gate/domain-filter-strip.tsx`
- `apps/web/widgets/approval-gate/score-pill.tsx`
- `apps/web/widgets/approval-gate/discovered-list.tsx`
- `apps/web/widgets/approval-gate/discovery-header.tsx`
- `apps/web/widgets/approval-gate/url-row.test.tsx`
- `apps/web/widgets/approval-gate/bulk-toolbar.test.tsx`
- `apps/web/features/run-mission/use-approval-state.ts`
- `apps/web/features/run-mission/use-approval-state.test.ts`
- `apps/web/features/run-mission/use-mission-phase.ts`
- `apps/web/features/run-mission/use-discovered-urls.ts`
- `apps/web/entities/mission/discovered-url.ts`

### Edit

- `apps/api/pyproject.toml` — add `tavily-python`
- `apps/api/.env.example` — append `TAVILY_API_KEY`
- `apps/api/app/config.py` — add `tavily_api_key` field
- `apps/api/app/agent.py` — add `build_discovery_agent`,
  `DiscoveryDeps`, `DiscoveryMissionResult`
- `apps/api/app/persistence/models.py` — add `MissionPhase`
  enum, four columns
- `apps/api/app/persistence/repository.py` — add `set_phase`,
  `set_discovered_urls`, `set_approved_urls`,
  `set_skip_approval`
- `apps/api/app/runner.py` — add approval registry,
  `start_description_mission`, `run_description_mission`
- `apps/api/app/routes.py` — polymorphic POST /missions,
  POST /missions/{id}/approve
- `packages/sse-protocol/schema.json` — add `DiscoveryComplete`
- `packages/sse-protocol/tests/round-trip.test.ts` — add case
- `apps/api/tests/test_sse_protocol.py` — add case
- `apps/web/widgets/command-palette/index.tsx` — add
  description-mode item
- `apps/web/widgets/mission-detail/index.tsx` — wire
  `SlideOverContent` state machine
- `apps/web/features/run-mission/use-submit-mission.ts` — add
  `submitDescription`
- `apps/web/features/run-mission/store.ts` — add description-
  mode slide-over open state
- `apps/web/app/api/missions/[id]/approve/route.ts` — new BFF
  route forwarding to api
- `apps/web/shared/i18n/keys/en.ts` — append 14 new keys

### Protected (do not touch)

- `apps/api/app/security.py`
- `apps/api/alembic/versions/0001_*.py` (past migration —
  add a new one)
- `packages/sse-protocol/generated/**` (regenerate; do not
  hand-edit)
- `apps/web/components/ui/*`
- All previous protected files

## Verification

Run from the repo root.

- `cd apps/api && uv sync` resolves `tavily-python`.
- `cd apps/api && uv run alembic upgrade head` succeeds against
  the Neon dev branch; `\d missions` shows the four new columns
  and the `mission_phase` enum.
- `pnpm --filter @autumn/sse-protocol generate` regenerates TS +
  pydantic with `DiscoveryComplete` present.
- `turbo run lint` exits 0.
- `turbo run typecheck` exits 0 — strict mypy passes; the
  generated `SseEvent` discriminated union narrows for
  `discovery_complete`.
- `turbo run test` exits 0 across api + web + sse-protocol.
- `turbo run build` exits 0.

Manual:

- With Clerk + Neon + R2 + LLM keys + Langfuse + Tavily set:
  - Cmd+K → "New description-mode mission" → slide-over opens.
  - Type "popular AI agent frameworks 2026", submit.
  - Slide-over reveals discovery state: rows append as
    `url_discovered` events arrive (~5 results in ~2s).
  - On `discovery_complete`, the approval gate renders. Default
    state: all checked except score < 0.4 rows (dimmed,
    unchecked).
  - Click a URL's hostname — inline edit input appears; modify
    path; press Enter; row shows `edited` tag.
  - Click a domain chip — list filters.
  - Cmd+A toggles all; deselect a few; Cmd+Enter submits.
  - Slide-over transitions to scraping state — `TaskLaneStack`
    renders the N approved URLs as concurrent task lanes.
  - Mission terminates with `done`.
- Close the slide-over mid-discovery — mission stays running on
  the api side; sidebar shows the mission. Re-open — approval
  gate re-renders from the persisted `discovered_urls`.
- Toggle the "Skip approval for this mission's future searches"
  checkbox before approving; on submit, `missions.skip_approval`
  flips to true in Neon.
- Force a Tavily 0-results path (e.g., a query for
  `"asdfqwerzxcv"`) — the gate shows `No results for this query`
  + Refine query button.
- Force a Tavily 5xx (mock the api key to an invalid one in
  dev) — the gate shows the rate-limited / paused message.
- Submit approval after the mission has already advanced past
  `awaiting_approval` (race condition simulation) — the api
  responds 409.
- A second user cannot POST `/missions/{id}/approve` for the
  first user's mission — RLS hides the row; repository returns
  None; endpoint responds 404.

## Done when

- [ ] Every Verification line passes.
- [ ] No invariant in `context/architecture.md` violated.
  Specifically:
  - Invariant 1 — `assert_safe_url` runs on every URL in
    `/approve` before parking the runner.
  - Invariant 4 — discovery and scraping share one
    per-mission queue; ring buffer covers the whole mission.
  - Invariant 7 — mission row writes precede every SSE event
    for that entity.
  - Invariant 10 — `_run_task` (Spec 10) still re-checks the
    mission row's status before any tool egress.
- [ ] `apps/api/app/security.py` was not edited.
- [ ] `apps/web/components/ui/*` was not edited.
- [ ] `prompt-engineer` agent rules pass: `build_discovery_agent`
  declares `output_type=DiscoveryMissionResult`; every run is
  Langfuse-traced.
- [ ] `i18n-keeper` agent flags zero hardcoded English in
  the new web files.
- [ ] `fsd-architect` agent flags zero layer violations.
- [ ] `context/progress-tracker.md` updated: Spec 12 to
  "Completed"; Spec 13 to "In Progress"; the open question
  about Tavily vs Exa stays in Open Questions (revisit after
  real-world quality data).
- [ ] `scrape-pipeline-doctor` agent run on `apps/api/**` finds
  zero violations.
- [ ] `sse-streaming-reviewer` agent run on the new
  `discovery_complete` event path finds zero violations against
  the Spec 06 contract.
- [ ] `migration-doctor` agent run on
  `apps/api/alembic/versions/0002_*.py` and the
  `missions` model changes (new `phase`, `skip_approval`,
  `discovered_urls`, `approved_urls` columns) confirms the
  `phase` enum and the schema additions are migration-safe.
- [ ] `llm-cost-guard` agent run on the discovery agent + the
  Tavily provider confirms the per-mission cost cap (max 1
  search, max 20 results) is enforced before any external
  egress, and the approval-wait timeout is bounded at 30 min.
- [ ] `code-reviewer` agent run on the chunk produces
  `CODE_REVIEW.md` with `Verdict: Approve`.
- [ ] `simplify` skill review on the diff returns no actionable
  findings.

## Scrape reliability note

This spec adds the second mission mode and one more failure
surface. Reliability story for description-mode:

1. **Tavily failure stops the mission cleanly.** A 5xx or rate-
   limit emits a typed `error` event with code
   `discovery_failed` plus a terminal `done` (failed). The
   user sees the named cause; no partial scrape happens.
2. **Approval timeout is bounded.** A mission parked in
   `awaiting_approval` for more than 30 minutes is `cancelled`
   automatically. Spec 14 may bring a reaper job for finer
   control, but the timeout in this spec prevents a forgotten
   mission from holding resources forever.
3. **Approved URLs revalidate at submit time.**
   `assert_safe_url` runs on every URL in the `/approve`
   payload — even if the user inline-edited a Tavily-supplied
   URL into a private-IP host, the SSRF guard catches it.
4. **Discovered URLs survive process restart.** The
   `discovered_urls` jsonb column persists the Tavily results;
   if the runner process dies, Spec 14's reaper can either
   recover (resume to awaiting_approval) or cancel — the data
   to make the call is in the DB.

What remains: per-lane cancel + reaper + cost surfacing
(Spec 14), adaptive selectors (Spec 13), production hardening
(Spec 15).
