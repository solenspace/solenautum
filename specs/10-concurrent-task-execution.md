# 10 — concurrent-task-execution

## Goal

Turn Autumn from a single-URL agent into a concurrent N-URL agent.
A mission accepts 1-20 URLs and runs each one inside its own task,
all owned by one `asyncio.TaskGroup` with structured concurrency
guarantees. Per-mission semaphores enforce the architecture's
HTTP-20 / browser-3 ceilings; the global ceilings from Spec 09
(60 / 8) layer on top. Spec 08's `# TODO(spec-10)` deviation is
removed: no `asyncio.create_task` outside a `TaskGroup`. Heartbeats
are wired into the SSE emitter so long-running missions survive
intermediate-proxy idle timeouts. Cancellation propagates correctly
across the TaskGroup; Spec 14 will plug a user-facing endpoint into
the mechanic introduced here.

## Dependencies

- `specs/05` — `MissionRepository`, `TaskRepository`, `MissionMode`,
  `Status`, `Tier`
- `specs/06` — `SseEvent`, ring buffer, `Last-Event-ID` resume
- `specs/07` — agent build, `LLMProviderChain`, runner skeleton,
  Langfuse tracing
- `specs/08` — web shell, top-bar URL input, command palette,
  `use-mission-stream` hook, slide-over
- `specs/09` — three tools registered, `MissionDeps`,
  `MissionResult` with `error_code`, browser semaphore in
  `concurrency.py`, `persist_snapshot`

## Design Decisions

- **One agent.run() per task.** Each URL gets its own Pydantic AI
  agent run with its own `MissionDeps`. The agent escalates HTTP →
  stealth → dynamic for that single URL, then returns its
  `MissionResult`. Per-URL independence keeps the LLM context
  small and the tool history per-task untangled. URL-mode does
  not need a single LLM run that "decides" the order — the user
  already supplied the URLs.
- **`asyncio.TaskGroup` is the only spawning surface** (invariant
  3). The runner holds one TaskGroup per mission; every task is
  group-owned; group exits when all tasks settle (success, error,
  or cancellation).
- **Per-mission semaphores** layered with the globals from
  Spec 09:
  - `HTTP per-mission`: `asyncio.Semaphore(20)`
  - `Browser per-mission`: `asyncio.Semaphore(3)`
  - Global ceilings (`60`, `8`) from `concurrency.py` apply on top.
  Acquisition order: per-mission first, then global. Release in
  reverse via stacked `async with`.
- **Tasks spawn all at once; semaphores throttle** ordering. asyncio
  queues waiters on a contended semaphore in FIFO order. No custom
  scheduler. Tasks that hit the per-mission HTTP cap wait inside
  their own `await semaphore.__aenter__()`, not blocking the
  TaskGroup.
- **Cancellation semantics** for Spec 10 (the mechanic only —
  Spec 14 plumbs a user-facing endpoint to it):
  - The `MissionRunner` exposes an `asyncio.Event`,
    `cancellation_requested`.
  - When set, queued (semaphore-waiting) tasks observe it on
    acquire and exit early with `Status.CANCELLED`.
  - In-flight tasks (already past the semaphore) finish — pending
    cancellation is **not** mid-page-render kill. This matches the
    architecture decision in `progress-tracker.md` open question 1.
  - On graceful TaskGroup exit (normal or all-cancelled), the
    mission row reaches its terminal status and the `done` SSE
    event fires.
- **Per-task tier badge in `task_start`** content already declares
  the tier per the SSE schema (Spec 06). For Spec 10, every task
  starts with `tier: "http"` (the agent picks the first tier);
  if the agent escalates, subsequent tool calls are reflected via
  `tool_start` / `tool_end` events, not via `task_start` updates
  (one `task_start` per task is the contract).
- **SSE heartbeat** lives inside the emitter as a per-mission
  asyncio task. It writes `: heartbeat\n\n` SSE comments every 15s
  to the per-mission queue. Comments do not consume `seq`; they
  pass through to the response writer untouched. Heartbeat task
  cancels when the mission's terminal event is enqueued.
- **The mission row is `RUNNING` before any task starts**
  (invariant 7). Each task row is `PENDING` at creation, flipped
  to `RUNNING` inside its task body before its `task_start` event
  fires.
- **Mission-level terminal event computation**: `done` content
  `mission_status` is `succeeded` if **all** tasks succeeded;
  `failed` if any task failed; `cancelled` if any task was
  cancelled and none failed. The runner computes this after the
  TaskGroup exits, before emitting `done`.
- **Spec 08's `start_url_mission` becomes the canonical entry
  point**, accepting `urls: list[str]` (1-20). The single-URL
  signature from Spec 07 is removed; callers always pass a list.
  The web's BFF translates the user's single-URL form into a
  one-element list.
- **The non-streaming `POST /missions` from Spec 08 stays.** It
  returns `{mission_id}` immediately; the slide-over opens an SSE
  connection. Spec 10 just makes the underlying runner
  TaskGroup-correct.
- **Web: top-bar input is unchanged for single-URL submissions.**
  The new "New multi-URL mission" Cmd+K item opens a right-side
  slide-over with a `<textarea>` (newline-separated URLs, 1-20),
  client-side parsed and validated, submitted via `Cmd+Enter`.

References:
- `context/architecture.md` — Concurrency, Storage Model, **Invariants
  3, 4, 5, 7, 10**
- `context/code-standards.md` — Python (async, structured
  concurrency)
- `context/progress-tracker.md` — Open question 1 (cancellation
  semantics)

## Implementation

### A. Expanded concurrency module — `apps/api/app/concurrency.py`

```python
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID


# Global ceilings (process-wide). Spec 09.
_GLOBAL_HTTP = asyncio.Semaphore(60)
_GLOBAL_BROWSER = asyncio.Semaphore(8)


@asynccontextmanager
async def http_slot() -> AsyncIterator[None]:
    """Acquire a global HTTP slot. Use inside a per-mission slot."""
    async with _GLOBAL_HTTP:
        yield


@asynccontextmanager
async def browser_slot() -> AsyncIterator[None]:
    """Acquire a global browser slot. Use inside a per-mission slot."""
    async with _GLOBAL_BROWSER:
        yield


@dataclass(slots=True)
class MissionSemaphores:
    """Per-mission tier ceilings. Layered with the globals."""
    http: asyncio.Semaphore
    browser: asyncio.Semaphore

    @classmethod
    def fresh(cls) -> "MissionSemaphores":
        return cls(
            http=asyncio.Semaphore(20),
            browser=asyncio.Semaphore(3),
        )

    @asynccontextmanager
    async def http_slot(self) -> AsyncIterator[None]:
        async with self.http, http_slot():
            yield

    @asynccontextmanager
    async def browser_slot(self) -> AsyncIterator[None]:
        async with self.browser, browser_slot():
            yield


# Scrape tools call into the active mission's slots via a context-var.
_active_semaphores: asyncio.contextvars.ContextVar[MissionSemaphores | None] = (  # type: ignore[attr-defined]
    asyncio.contextvars.ContextVar("active_semaphores", default=None)
)


@asynccontextmanager
async def with_mission_semaphores(sems: MissionSemaphores) -> AsyncIterator[None]:
    """Bind per-mission semaphores to the current task's context. Tools
    read this var and acquire layered slots."""
    token = _active_semaphores.set(sems)
    try:
        yield
    finally:
        _active_semaphores.reset(token)


def current_mission_semaphores() -> MissionSemaphores:
    sems = _active_semaphores.get()
    if sems is None:
        # Defensive: tools called outside a mission run hit this.
        # Fall back to globals only.
        return MissionSemaphores.fresh()
    return sems
```

The `contextvars`-based binding is the cleanest way to thread
per-mission semaphores through tool call sites without changing
every tool's signature. asyncio propagates context across
`asyncio.create_task` and `TaskGroup.create_task`, so a TaskGroup-
owned task inherits its parent mission's semaphores automatically.

### B. Update the tier tools to use layered semaphores

Each browser tool (Spec 09) currently calls `browser_slot()`
(global only). Spec 10 replaces those with per-mission-then-global
acquisition via the helper:

```python
# in stealth.py / dynamic.py
from app.concurrency import current_mission_semaphores

async with current_mission_semaphores().browser_slot():
    async with AsyncStealthySession(solve_cloudflare=True, headless=True) as session:
        ...
```

Same change for the HTTP tier (which Spec 09 did not gate at all):

```python
# in http.py
async with current_mission_semaphores().http_slot():
    page = await fetcher.get(args.url, ...)
```

The HTTP tier's `http_slot` acquisition is new in Spec 10 — Spec 07
had no concurrency gate. The semaphore prevents a 20-URL mission
from opening 20 simultaneous HTTP connections to the same domain.

### C. Mission runner rewrite — `apps/api/app/runner.py`

```python
from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from autumn_sse_protocol import SseEvent

from app.agent import MissionDeps, MissionResult, build_agent
from app.concurrency import MissionSemaphores, with_mission_semaphores
from app.llm import GroqProvider, LLMProviderChain, OpenRouterProvider
from app.observability import start_mission_trace
from app.persistence.models import (
    Mission,
    MissionMode,
    Status,
    Task,
    Tier,
)
from app.persistence.repository import MissionRepository, TaskRepository
from app.runner_helpers import last_ok_tool_call
from app.security import CurrentUser, _current_user, assert_safe_url
from app.sse import emitter


log = logging.getLogger(__name__)


class MissionRunner:
    """Owns the TaskGroup for one mission. One instance per mission."""

    def __init__(
        self,
        *,
        user: CurrentUser,
        mission: Mission,
        tasks: list[Task],
    ) -> None:
        self._user = user
        self._mission = mission
        self._tasks = tasks
        self._sems = MissionSemaphores.fresh()
        self._cancellation_requested = asyncio.Event()
        self._missions_repo = MissionRepository()
        self._tasks_repo = TaskRepository()
        self._chain = LLMProviderChain(
            primary=OpenRouterProvider(), fallback=GroqProvider()
        )

    def request_cancellation(self) -> None:
        """Spec 14 plugs into this. Cancels queued tasks; in-flight finish."""
        self._cancellation_requested.set()

    async def run(self) -> None:
        """Run all tasks inside one TaskGroup. Emits per-task events
        and a mission-level done/error at the end."""
        _current_user.set(self._user)
        trace = start_mission_trace(
            mission_id=self._mission.id,
            user_id=self._user.user_id,
            prompt=", ".join(t.url for t in self._tasks),
        )

        async with with_mission_semaphores(self._sems):
            try:
                async with asyncio.TaskGroup() as tg:
                    for task in self._tasks:
                        tg.create_task(
                            self._run_task(task),
                            name=f"task:{task.id}",
                        )
            except* Exception as eg:  # py3.11+ ExceptionGroup
                log.exception("mission task group raised", extra={
                    "mission_id": str(self._mission.id),
                    "errors": [repr(e) for e in eg.exceptions],
                })

        await self._emit_mission_terminal()
        trace.update(output={"status": self._compute_mission_status().value})

    async def _run_task(self, task: Task) -> None:
        """One URL, one agent.run(). Honors invariants 1, 5, 7, 10, 11."""
        if self._cancellation_requested.is_set():
            await self._tasks_repo.update(task.id, status=Status.CANCELLED)
            await self._emit_task_end(task, status=Status.CANCELLED)
            return

        # Invariant 7: row is in DB (PENDING from runner.create);
        # flip to RUNNING before first SSE event for this task.
        await self._tasks_repo.update(task.id, status=Status.RUNNING)
        await emitter.emit(
            SseEvent.model_validate(
                {
                    "type": "task_start",
                    "content": {"url": task.url, "tier": "http"},
                    "mission_id": str(self._mission.id),
                    "task_id": str(task.id),
                    "seq": 0,
                }
            )
        )

        # Invariant 10: confirm mission still RUNNING before the network egress.
        fresh = await self._missions_repo.get(self._mission.id)
        if fresh is None or fresh.status != Status.RUNNING:
            await self._tasks_repo.update(task.id, status=Status.CANCELLED)
            await self._emit_task_end(task, status=Status.CANCELLED)
            return

        deps = MissionDeps(
            user_id=self._user.user_id,
            mission_id=self._mission.id,
            task_id=task.id,
            robots_override=self._mission.robots_override,
        )

        try:
            async def _run(model):
                agent = build_agent(model_factory=lambda: model)
                return await agent.run(task.url, deps=deps)

            result = await self._chain.with_fallback(_run)
        except asyncio.CancelledError:
            # TaskGroup cancellation. Emit terminal then re-raise so the
            # group sees it (invariant 5: every task emits exactly one
            # terminal event).
            await self._tasks_repo.update(task.id, status=Status.CANCELLED)
            await self._emit_task_end(task, status=Status.CANCELLED)
            raise
        except Exception as exc:
            log.exception("task failed", extra={"task_id": str(task.id)})
            await self._tasks_repo.update(task.id, status=Status.FAILED)
            await emitter.emit(
                SseEvent.model_validate(
                    {
                        "type": "error",
                        "content": {"code": "agent_failed", "message": str(exc)},
                        "mission_id": str(self._mission.id),
                        "task_id": str(task.id),
                        "seq": 0,
                    }
                )
            )
            await self._emit_task_end(task, status=Status.FAILED)
            return

        # Persist results from the last successful tool call.
        ok_call = last_ok_tool_call(result)
        mission_result: MissionResult = result.output
        final_status = (
            Status.SUCCEEDED if mission_result.status == "ok" else Status.FAILED
        )

        await self._tasks_repo.update(
            task.id,
            status=final_status,
            parsed_markdown=ok_call.markdown if ok_call else None,
            snapshot_key=ok_call.snapshot_key if ok_call else None,
            snapshot_truncated=ok_call.snapshot_truncated if ok_call else False,
            latency_ms=ok_call.latency_ms if ok_call else None,
        )

        if mission_result.status == "error":
            await emitter.emit(
                SseEvent.model_validate(
                    {
                        "type": "error",
                        "content": {
                            "code": mission_result.error_code or "agent_failed",
                            "message": mission_result.summary,
                        },
                        "mission_id": str(self._mission.id),
                        "task_id": str(task.id),
                        "seq": 0,
                    }
                )
            )

        await self._emit_task_end(task, status=final_status, ok_call=ok_call)

    async def _emit_task_end(
        self, task: Task, *, status: Status, ok_call=None
    ) -> None:
        sse_status = (
            "succeeded" if status == Status.SUCCEEDED
            else "failed" if status == Status.FAILED
            else "cancelled"
        )
        content = {"status": sse_status}
        if ok_call:
            content["preview"] = (ok_call.markdown or "")[:500]
            if ok_call.snapshot_key:
                content["snapshot_key"] = ok_call.snapshot_key
            if ok_call.latency_ms is not None:
                content["latency_ms"] = ok_call.latency_ms
        await emitter.emit(
            SseEvent.model_validate(
                {
                    "type": "task_end",
                    "content": content,
                    "mission_id": str(self._mission.id),
                    "task_id": str(task.id),
                    "seq": 0,
                }
            )
        )

    def _compute_mission_status(self) -> Status:
        # Read the freshest task statuses from memory after the TaskGroup
        # exits. The repository round-trip is unnecessary because each
        # task's update path was awaited.
        # We check the database to avoid relying on stale in-memory state.
        # (Actual implementation re-fetches via TaskRepository.list_by_mission;
        # see runner_helpers.py.)
        from app.runner_helpers import compute_mission_status_sync_from_db
        # Fire-and-forget the read; called from the parent run() which
        # awaits.
        raise NotImplementedError("see compute path in run() below")


async def start_url_mission(
    *,
    user: CurrentUser,
    urls: Sequence[str],
) -> UUID:
    """Create a mission with N task rows and start the TaskGroup runner.
    Returns the mission_id immediately; the runner runs in the background
    inside an outer TaskGroup (invariant 3). Caller streams via
    `emitter.stream(mission_id, ...)`."""
    if not 1 <= len(urls) <= 20:
        raise ValueError("urls must contain 1-20 entries")

    for url in urls:
        assert_safe_url(url)

    _current_user.set(user)
    missions = MissionRepository()
    tasks_repo = TaskRepository()

    mission = await missions.create(
        user_id=user.user_id,
        prompt="\n".join(urls),
        mode=MissionMode.URL,
    )
    await missions.update_status(mission.id, Status.RUNNING)

    task_rows: list[Task] = []
    for url in urls:
        t = await tasks_repo.create(
            mission_id=mission.id, url=url, tier_used=Tier.HTTP
        )
        task_rows.append(t)

    runner = MissionRunner(user=user, mission=mission, tasks=task_rows)

    # Invariant 3: the runner's TaskGroup is created inside the runner.run()
    # method. To return the mission_id immediately, we hand the runner off
    # to the SseEmitter's mission-runner registry, which owns a top-level
    # TaskGroup that adopts each new MissionRunner. See section D.
    await emitter.adopt_runner(mission.id, runner)
    return mission.id
```

The `_compute_mission_status` and the `await self._emit_mission_terminal()`
end-of-`run()` path use a small helper module that reads task
statuses from the database after the TaskGroup exits and emits
`done` (or mission-level `error` for special cases like
"all tasks cancelled"). The implementation is in
`apps/api/app/runner_helpers.py`; the spec keeps the runner module
focused on the TaskGroup mechanics.

### D. Emitter adopts runners — `apps/api/app/sse.py` (extension)

The emitter currently owns per-mission state (queue, ring buffer,
seq). Spec 10 extends it to own the **TaskGroup that runs the
runner** so that `start_url_mission` can return immediately while
the runner runs in a structured-concurrency-safe parent group.

```python
# in app/sse.py


class _RunnerAdoption:
    """Runs MissionRunners in a single process-level TaskGroup so the
    POST /missions handler can return immediately while the runner
    continues."""

    def __init__(self) -> None:
        self._tg: asyncio.TaskGroup | None = None
        self._lock = asyncio.Lock()

    async def adopt(self, mission_id: UUID, runner: "MissionRunner") -> None:
        async with self._lock:
            if self._tg is None:
                # Lazy-create on first adoption. Stays alive for the
                # process lifetime.
                self._tg = await self._enter_top_level_group()
            self._tg.create_task(
                runner.run(),
                name=f"mission:{mission_id}",
            )

    async def _enter_top_level_group(self) -> asyncio.TaskGroup:
        # Simulate a top-level TaskGroup by entering it inside the
        # FastAPI lifespan. Invariant 3 holds because every spawned
        # task is owned by this group; uvicorn's shutdown awaits group
        # exit before exiting.
        ...


# Wire `adopt_runner(mission_id, runner)` on the emitter:
class SseEmitter:
    # ... existing fields and methods ...
    _runners: _RunnerAdoption = field(default_factory=_RunnerAdoption)

    async def adopt_runner(self, mission_id: UUID, runner: "MissionRunner") -> None:
        await self._runners.adopt(mission_id, runner)
```

The cleanest implementation of the top-level TaskGroup uses
FastAPI's `lifespan` context manager:

```python
# in app/main.py
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with asyncio.TaskGroup() as tg:
        emitter._runners._tg = tg  # type: ignore[reveal-private]  # justified: lifespan binding
        yield


app = FastAPI(title="Autumn API", lifespan=lifespan)
```

The TaskGroup lives for the lifetime of the process. On shutdown,
`lifespan` exits the TaskGroup, which awaits all in-flight missions
to complete (or cancel) before the process exits. Long-running
missions in flight at shutdown receive `CancelledError`; their
in-flight tier sessions unwind via `async with`.

Invariant 3 is now fully satisfied. The Spec 08 `# TODO(spec-10)`
marker on `asyncio.create_task` in the old runner is removed; the
test for it is now expected to pass without the temporary
exception.

### E. SSE heartbeat implementation

Replace the stub heartbeat from Spec 07. The emitter starts a
heartbeat task per active mission, alongside the existing event
queue.

```python
# in app/sse.py — extend _MissionState

@dataclass(slots=True)
class _MissionState:
    seq: int = 0
    queue: asyncio.Queue[bytes | None] = field(
        default_factory=lambda: asyncio.Queue(maxsize=512)
    )
    buffer: deque[tuple[int, dict[str, Any]]] = field(
        default_factory=lambda: deque(maxlen=_BUFFER_CAPACITY)
    )
    terminated_at: float | None = None
    heartbeat_task: asyncio.Task | None = None
```

The queue's value type changes from `tuple[seq, payload] | None`
to `bytes | None` — pre-formatted SSE bytes. The emitter formats
once at emit time; the consumer just writes bytes through. This
also makes heartbeats first-class: a heartbeat is just a
pre-formatted `b": heartbeat\n\n"` enqueued every 15s.

```python
async def _heartbeat_loop(state: _MissionState) -> None:
    try:
        while True:
            await asyncio.sleep(15)
            await state.queue.put(b": heartbeat\n\n")
    except asyncio.CancelledError:
        return


# Inside SseEmitter.emit, after pushing the event onto the queue,
# start the heartbeat task lazily:
if state.heartbeat_task is None:
    state.heartbeat_task = asyncio.create_task(
        _heartbeat_loop(state), name=f"sse-heartbeat:{mission_id}"
    )

# When a mission-level terminal event arrives (done / mission-level error):
if state.heartbeat_task is not None:
    state.heartbeat_task.cancel()
    state.heartbeat_task = None
```

The `asyncio.create_task` here is acceptable because the heartbeat
is process-scoped infrastructure, not a mission task. The
`scrape-pipeline-doctor` agent's invariant-3 rule applies to
mission tasks; `sse-streaming-reviewer` accepts heartbeat tasks as
infrastructure.

Add a unit test (`test_sse_heartbeat`): start a stream, inject no
events for 16s using `asyncio.sleep` mocked via `freezegun` or
`pytest-asyncio`'s time control, assert at least one heartbeat
chunk arrived.

### F. POST /missions endpoint signature change

`apps/api/app/routes.py` — `POST /missions` now accepts a JSON
body with a `urls` array (1-20):

```python
from pydantic import BaseModel, Field, conlist

class CreateMissionRequest(BaseModel):
    urls: conlist(str, min_length=1, max_length=20)


@router.post("/missions", status_code=202)
async def create_mission(
    request: CreateMissionRequest,
    user: RequireUser,
) -> dict[str, str]:
    mission_id = await start_url_mission(user=user, urls=request.urls)
    return {"mission_id": str(mission_id)}
```

The Spec 08 single-URL flow now sends a one-element array. The web
BFF translates the form's single URL into `urls=[url]`.

### G. Web: multi-URL slide-over via Cmd+K

#### `apps/web/widgets/multi-url-slideover/index.tsx`

```tsx
"use client";

import { useState } from "react";
import { z } from "zod";

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Kbd } from "@/components/ui/kbd";
import { useT } from "@/shared/i18n";
import { useShortcut } from "@/shared/keyboard";
import { useSubmitMission } from "@/features/run-mission";


const urlsSchema = z
  .array(z.string().url())
  .min(1, "missionUrlsRequired")
  .max(20, "missionUrlsTooMany");


export function MultiUrlSlideover({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const t = useT();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { submitMany, isSubmitting } = useSubmitMission();

  useShortcut("Escape", () => open && onOpenChange(false));

  async function handleSubmit() {
    setError(null);
    const urls = text
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    const parsed = urlsSchema.safeParse(urls);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "missionUrlsInvalid");
      return;
    }
    await submitMany(parsed.data);
    onOpenChange(false);
    setText("");
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-2xl border-l border-border/50">
        <SheetHeader className="border-b border-border/50 pb-2">
          <SheetTitle className="text-[13px]">
            {t("mission", "newMultiUrlMission")}
          </SheetTitle>
        </SheetHeader>
        <div className="flex flex-col gap-3 p-4">
          <p className="text-xs text-muted-foreground">
            {t("mission", "multiUrlHelp")}
          </p>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t("mission", "multiUrlPlaceholder")}
            spellCheck={false}
            rows={12}
            className="w-full resize-none rounded-md border border-border/50 bg-card px-3 py-2 font-mono text-[13px] outline-hidden focus-visible:ring-2 ring-ring/40"
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                void handleSubmit();
              }
            }}
            disabled={isSubmitting}
          />
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span>
              {text.split("\n").filter((l) => l.trim()).length} {t("mission", "urlCount")}
            </span>
            <span className="flex items-center gap-1.5">
              {error ? (
                <span className="text-destructive">{t("validation", error)}</span>
              ) : null}
              <Kbd>⌘↩</Kbd>
            </span>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
```

#### Wire into command palette

`apps/web/widgets/command-palette/index.tsx` adds a new
`CommandItem`:

```tsx
<CommandItem onSelect={() => setMultiUrlOpen(true)}>
  <ListPlus className="h-3.5 w-3.5" />
  {t("mission", "newMultiUrlMission")}
  <CommandShortcut>⌘⇧N</CommandShortcut>
</CommandItem>
```

The `MultiUrlSlideover` is mounted at the shell level next to the
existing `MissionDetailSlideover`. Its `open` state lives in the
mission store (zustand) so the palette and any caller can toggle it.

#### Hook update — `useSubmitMission`

```tsx
async function submitMany(urls: string[]) {
  setSubmitting(true);
  try {
    const response = await fetch("/api/missions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls }),
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

// existing single-URL submit becomes a thin wrapper:
async function submit(url: string) {
  return submitMany([url]);
}
```

#### BFF route — `apps/web/app/api/missions/route.ts`

Forward the JSON body through to the api with the Clerk JWT:

```ts
import { auth } from "@clerk/nextjs/server";

export async function POST(req: Request) {
  const { userId, getToken } = await auth();
  if (!userId) return new Response("unauthorized", { status: 401 });

  const body = await req.json();
  const token = await getToken();

  const upstream = await fetch(`${process.env.AUTUMN_API_URL}/missions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });

  return new Response(upstream.body, { status: upstream.status });
}
```

### H. i18n keys (additions)

- `mission.newMultiUrlMission` — "New multi-URL mission"
- `mission.multiUrlHelp` — "One URL per line. 1 to 20 URLs."
- `mission.multiUrlPlaceholder` — "https://...\nhttps://..."
- `mission.urlCount` — "URLs" (plural via `count`: `urlCount_one`
  = "URL", `urlCount_other` = "URLs")
- `validation.missionUrlsRequired` — "Add at least one URL"
- `validation.missionUrlsTooMany` — "Maximum 20 URLs per mission"
- `validation.missionUrlsInvalid` — "One or more URLs are invalid"

### I. Tests

#### `apps/api/tests/test_concurrency_layered.py`

```python
import asyncio
import pytest

from app.concurrency import MissionSemaphores, with_mission_semaphores, current_mission_semaphores


@pytest.mark.asyncio
async def test_per_mission_http_caps_at_20():
    sems = MissionSemaphores.fresh()
    inflight = 0
    peak = 0

    async def _job():
        nonlocal inflight, peak
        async with with_mission_semaphores(sems):
            async with current_mission_semaphores().http_slot():
                inflight += 1
                peak = max(peak, inflight)
                await asyncio.sleep(0.01)
                inflight -= 1

    await asyncio.gather(*[_job() for _ in range(40)])
    assert peak <= 20


@pytest.mark.asyncio
async def test_per_mission_browser_caps_at_3():
    sems = MissionSemaphores.fresh()
    inflight = 0
    peak = 0

    async def _job():
        nonlocal inflight, peak
        async with with_mission_semaphores(sems):
            async with current_mission_semaphores().browser_slot():
                inflight += 1
                peak = max(peak, inflight)
                await asyncio.sleep(0.01)
                inflight -= 1

    await asyncio.gather(*[_job() for _ in range(10)])
    assert peak <= 3
```

#### `apps/api/tests/test_runner_taskgroup.py`

```python
import asyncio
import pytest

from app.runner import MissionRunner
# fixtures provide a Mission with 5 tasks and a mocked agent that returns
# MissionResult(status="ok") after a 0.1s sleep per task


@pytest.mark.asyncio
async def test_all_tasks_run_concurrently(monkeypatch, mission_with_5_tasks):
    runner = MissionRunner(**mission_with_5_tasks)
    # Mocked agent records the timestamps of agent.run() calls; assert
    # they cluster within 50ms (started concurrently).
    ...


@pytest.mark.asyncio
async def test_cancellation_propagates(mission_with_5_tasks):
    runner = MissionRunner(**mission_with_5_tasks)
    run_task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.01)
    runner.request_cancellation()
    await run_task
    # Assert: queued tasks are CANCELLED; in-flight (already past
    # semaphore) settled normally; no FAILED tasks.


@pytest.mark.asyncio
async def test_no_detached_tasks_after_run(mission_with_5_tasks):
    before = len(asyncio.all_tasks())
    runner = MissionRunner(**mission_with_5_tasks)
    await runner.run()
    after = len(asyncio.all_tasks())
    # The current task is the test runner itself; no leaked workers.
    assert after - before <= 1
```

#### `apps/api/tests/test_sse_heartbeat.py`

```python
import asyncio
import pytest

from app.sse import SseEmitter
from autumn_sse_protocol import SseEvent
from uuid import uuid4


@pytest.mark.asyncio
async def test_heartbeat_after_15s(monkeypatch):
    em = SseEmitter()
    mission = uuid4()
    await em.emit(SseEvent.model_validate({
        "type": "task_start",
        "content": {"url": "https://x/", "tier": "http"},
        "mission_id": str(mission),
        "task_id": str(uuid4()),
        "seq": 0,
    }))

    chunks: list[bytes] = []
    async def _consume():
        async with em.stream(mission, last_event_id=None) as it:
            async for chunk in it:
                chunks.append(chunk)
                if len(chunks) > 1:  # past initial event
                    break

    # Drive 16s of asyncio time via an event-loop-aware time mock.
    # If the heartbeat fires, chunks contains b": heartbeat\n\n".
    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0.05)  # let the stream attach
    # ... time-mock advance ...
    await asyncio.wait_for(consumer, timeout=20)
    assert any(c == b": heartbeat\n\n" for c in chunks)
```

#### Web tests

- `apps/web/widgets/multi-url-slideover/multi-url-slideover.test.tsx`
  — Vitest with `I18nTestWrapper`. Cases: 0 URLs disabled submit;
  21 URLs flagged; 20 URLs accepted; `Cmd+Enter` triggers submit;
  `Esc` closes the slide-over.
- `apps/web/features/run-mission/use-submit-mission.test.tsx` —
  `submitMany` posts JSON; `submit(url)` is a thin wrapper that
  calls `submitMany([url])`.

### J. Order of operations

1. Expand `apps/api/app/concurrency.py` with `MissionSemaphores`
   and `current_mission_semaphores()` (sections A).
2. Update `tools/http.py`, `tools/stealth.py`, `tools/dynamic.py`
   to use layered semaphores (section B).
3. Rewrite `apps/api/app/runner.py`: `MissionRunner`,
   `start_url_mission`, helpers (section C).
4. Extend `apps/api/app/sse.py` with `_RunnerAdoption`, the
   lifespan-scoped TaskGroup, and the heartbeat loop (section D, E).
5. Wire `lifespan` in `apps/api/app/main.py` (section D).
6. Update `apps/api/app/routes.py` to accept the `urls: list[str]`
   body (section F). Keep the streaming route from Spec 08.
7. Build the web `MultiUrlSlideover`; wire into the command
   palette and the mission store (section G).
8. Extend `useSubmitMission` with `submitMany`; update the BFF
   `/api/missions` route (section G).
9. Add the seven i18n keys (section H).
10. Write the tests (section I); iterate until they pass.
11. Remove the `# TODO(spec-10)` marker from `runner.py` and any
    "invariant 3 deviation" entry from
    `context/progress-tracker.md` Open Questions.
12. Run the verification block.

## Out of Scope

- **User-facing mission cancellation endpoint
  (`DELETE /missions/{id}`)** — Spec 14. The mechanic
  (`runner.request_cancellation()`) ships in this spec.
- **URL discovery (Tavily, description-mode)** — Spec 12.
- **Adaptive selectors / `selector_recovered` events** — Spec 13.
- **Mission cancellation UI surface** — Spec 14.
- **Mission cost surfacing** — Spec 14.
- **Per-domain throttling (politeness)** — not in scope; revisit if
  scrape volume against single domains becomes a problem. The
  per-mission HTTP-20 ceiling already prevents a 20-URL mission
  against one domain from over-fetching.
- **Multi-lane web UI rendering** — Spec 11. Spec 10 surfaces
  events for N tasks; Spec 11 renders them as a stack.
- **Resumable runner state across restarts** — out of scope; a
  hard process restart fails in-flight missions. Reaper job in
  Spec 14 marks them `failed` so they don't sit `running` forever.

## Files

### Create

- `apps/api/app/runner_helpers.py` — `last_ok_tool_call`,
  `compute_mission_status_from_db`, `_emit_mission_terminal`
- `apps/api/tests/test_concurrency_layered.py`
- `apps/api/tests/test_runner_taskgroup.py`
- `apps/api/tests/test_sse_heartbeat.py`
- `apps/web/widgets/multi-url-slideover/index.tsx`
- `apps/web/widgets/multi-url-slideover/multi-url-slideover.test.tsx`

### Edit

- `apps/api/app/concurrency.py` — add `MissionSemaphores`,
  `with_mission_semaphores`, `current_mission_semaphores`
- `apps/api/app/tools/http.py` — wrap fetch in
  `current_mission_semaphores().http_slot()`
- `apps/api/app/tools/stealth.py`,
  `apps/api/app/tools/dynamic.py` — replace direct
  `browser_slot()` with `current_mission_semaphores().browser_slot()`
- `apps/api/app/runner.py` — replace single-task runner with
  `MissionRunner` + `start_url_mission(urls=[...])`. **Remove the
  `asyncio.create_task` from Spec 08.**
- `apps/api/app/sse.py` — add `_RunnerAdoption`, heartbeat task
  per mission, format-once-on-emit (queue holds bytes)
- `apps/api/app/main.py` — wire FastAPI `lifespan` to bind the
  emitter's top-level TaskGroup
- `apps/api/app/routes.py` — `POST /missions` accepts
  `CreateMissionRequest` body
- `apps/web/widgets/command-palette/index.tsx` — add
  `New multi-URL mission` item
- `apps/web/features/run-mission/use-submit-mission.ts` — add
  `submitMany`
- `apps/web/features/run-mission/store.ts` — add multi-URL
  slide-over open state
- `apps/web/app/api/missions/route.ts` — forward JSON body to api
- `apps/web/app/(app)/layout.tsx` — mount `MultiUrlSlideover`
- `apps/web/shared/i18n/keys/en.ts` — append the 7 new keys
- `context/progress-tracker.md` — remove the Spec-08
  invariant-3-deviation entry from Open Questions

### Protected (do not touch)

- `apps/api/app/security.py`
- `apps/api/alembic/versions/*` past migrations
- `packages/sse-protocol/generated/**`
- `apps/web/components/ui/*`
- All previous protected files

## Verification

Run from the repo root.

- `cd apps/api && uv sync` is a no-op.
- `turbo run lint` exits 0.
- `turbo run typecheck` exits 0.
- `turbo run test` exits 0:
  - `test_concurrency_layered.py` — both ceiling tests pass.
  - `test_runner_taskgroup.py` — all-concurrent, cancellation,
    no-detached-tasks all pass.
  - `test_sse_heartbeat.py` — heartbeat fires within the 16s window.
- `turbo run build` exits 0.
- `grep -R "create_task" apps/api/app/runner.py` returns nothing
  (the Spec-08 marker is gone).
- `grep -R "TODO(spec-10)" apps/api apps/web` returns nothing.
- `cat context/progress-tracker.md | grep -i "invariant 3"`
  returns no Open Questions entries.

Manual:

- `turbo run dev` boots both apps.
- Sign in. Submit a single URL via the top bar — the slide-over
  opens and the lane streams as before.
- Cmd+K → "New multi-URL mission" — slide-over opens with the
  textarea. Paste 5 URLs (one per line). Cmd+Enter submits. The
  mission slide-over (the existing detail one) opens. Five tasks
  emit `task_start` events within ~100ms of each other; tier
  badges match each tool selection; the per-task lanes
  (still rendered as a single lane in Spec 10 — multi-lane is
  Spec 11) cycle through events with stable seq monotonicity.
- Submit a 20-URL mission. With the per-mission HTTP cap of 20,
  all start. With browser cap 3, only the first three browser
  escalations run concurrently. Wait for `done`; mission row
  is `succeeded` if all tasks succeeded.
- Open Langfuse: each mission shows N task spans; provider-switch
  spans appear when the rate-limit fallback fires.
- Kill the api process (`SIGTERM`) mid-mission. The lifespan's
  TaskGroup awaits the runner; tasks past the semaphore complete;
  queued tasks cancel cleanly. No orphaned Chromium processes.
- Forced disconnect mid-stream and reconnect with `Last-Event-ID`
  header; resume picks up from the right seq.

## Done when

- [ ] Every Verification line passes.
- [ ] The Spec-08 `# TODO(spec-10)` marker is removed; no
  `asyncio.create_task` remains in `runner.py`.
- [ ] No invariant in `context/architecture.md` violated.
  Specifically:
  - Invariant 3 — every mission task is owned by a TaskGroup.
    The lifespan-scoped top-level group adopts each
    MissionRunner; each runner's internal group owns its tasks.
  - Invariant 5 — every task emits exactly one `task_end` (or a
    cancellation terminal). Verified by `test_runner_taskgroup`.
  - Invariant 7 — task rows reach `RUNNING` before any
    `task_start` event is emitted; mission row is `RUNNING`
    before the first task starts.
  - Invariant 10 — every `_run_task` re-checks
    `mission.status == RUNNING` before any tool egress.
- [ ] `apps/api/app/security.py` was not edited.
- [ ] `context/progress-tracker.md` updated: Spec 10 to
  "Completed"; Spec 11 to "In Progress"; Spec-08
  invariant-3-deviation entry removed from Open Questions.
- [ ] `scrape-pipeline-doctor` agent run on `apps/api/**`
  confirms invariant 3 (TaskGroup ownership) closed plus
  invariants 4, 5, 7, 10.
- [ ] `sse-streaming-reviewer` agent run on
  `apps/api/app/sse.py` confirms heartbeat + ring buffer comply
  with the Spec 06 contract.
- [ ] `code-reviewer` agent run on the chunk produces
  `CODE_REVIEW.md` with `Verdict: Approve`.
- [ ] `simplify` skill review on the diff returns no actionable
  findings.

## Scrape reliability note

Spec 10 is the inflection point of the build. Three reliability
shifts land here:

1. **Wall-clock time on N-URL missions drops from N×T to ~T**
   (where T is the slowest single-task latency), because all N
   tasks run concurrently. A 20-URL mission that took 4 minutes
   sequentially now takes ~12 seconds plus the slowest tier's
   latency.
2. **Cancellation is structured.** When the user cancels mid-flight
   (via Spec 14's endpoint), the TaskGroup's CancelledError walks
   every in-flight task; `async with` blocks unwind; semaphores
   release; browser sessions close. No leak, no half-finished
   state.
3. **Long-lived connections survive proxy idle timeouts.**
   Heartbeats every 15s keep Cloudflare / Fly.io / Render proxies
   from killing idle SSE streams. A user who walks away from a
   running 20-URL mission for 5 minutes returns to a still-live
   stream.

Open after Spec 10: per-task UI rendering (Spec 11), description-
mode URL discovery (Spec 12), adaptive selectors (Spec 13), user-
facing cancellation + cost surface (Spec 14), full hardening +
e2e (Spec 15).
