# 14 — cost-and-mission-lifecycle

## Goal

Close every user-facing mission-lifecycle surface that earlier
specs deferred. After this spec: missions can be cancelled (whole
mission or single task), HTML snapshots are downloadable via a
1-hour signed R2 URL, per-mission token cost from Langfuse lands
on the sidebar entry and the lane footer, the orphan-mission
reaper marks stuck missions as cancelled within ~5-65 minutes of
their last activity, and the sidebar surfaces a new
`Awaiting approval` group for description-mode missions parked
on the approval gate.

## Dependencies

- `specs/05` — `BlobStore.signed_url`, missions / tasks tables
- `specs/07` — Langfuse trace start; missions write cost back at
  terminal
- `specs/10` — `MissionRunner.request_cancellation()` mechanic;
  lifespan TaskGroup
- `specs/11` — `TaskLaneStack`, `TaskLaneRow` (cancel UI hooks),
  `MissionDetailSlideover` header
- `specs/12` — `phase` column, `awaiting_approval`, `MissionPhase`
  enum
- `specs/13` — selector sweep loop pattern (this spec adds a
  parallel reaper loop)

## Design Decisions

### Cancellation

- **Mission-level**: `DELETE /missions/{id}` calls
  `runner.request_cancellation()`. The runner's
  `cancellation_requested` event flips; queued tasks observe and
  exit `Status.CANCELLED`; in-flight tasks finish per the
  architecture rule.
- **Per-task**: `DELETE /missions/{id}/tasks/{task_id}` cancels
  one task within a still-running mission. If the task is
  pending (semaphore-waiting), it exits `Status.CANCELLED`
  immediately. If it is in-flight (past the semaphore), the
  endpoint records the cancel intent on the task row but lets
  the in-flight call finish — same architectural rule as
  mission-level. Future spec may introduce mid-render
  interruption.
- **UI surface**:
  - Mission-level: a `Cancel mission` text-button in the
    `MissionDetailSlideover` header. Visible only when
    `mission.status == "running"`. Esc still closes the
    slide-over without cancelling.
  - Per-task: `X` shortcut on the focused lane now cancels that
    task instead of clearing the pin (Spec 11's pin-clear was
    superseded). The pin behavior moves to a small icon button
    in the row body for the rare "I want to unpin without
    cancel" case.
- **Cancellation idempotency**: a second `DELETE` on an already-
  cancelled mission returns `204` with a `cancellation_pending`
  header so the client can stop polling.

### Cost computation

- **Cached column**: `missions.cost_cents` (already present in
  the schema from Spec 05) is written by the runner after the
  mission's terminal event fires. Source: Langfuse SDK's
  `trace.observations` + cost aggregation API.
- **Read path**: sidebar entries read `cost_cents` directly;
  lane footer shows the same value. No live Langfuse calls in
  the read path.
- **Failure mode**: if Langfuse is unreachable when writing the
  terminal cost, log the error and leave `cost_cents = 0`. A
  small "?" icon in the sidebar indicates "cost unavailable".
  Spec 15's hardening may add a retry / reconciliation step.

### Snapshot retrieval

- **`GET /missions/{id}/tasks/{task_id}/snapshot`** — verifies
  ownership via the repository (RLS backstop), returns a
  302 redirect to a freshly-generated signed R2 URL with 1-hour
  TTL. No persisted URL anywhere.
- **Web surface**: result preview in `TaskLaneRow` shows a
  `Download HTML` text-button below the markdown excerpt only
  when `task.snapshot_key != null`. Click → fetches the redirect
  → browser opens the gzipped HTML.
- **Local-fs blob store** (dev) returns a `file://` URL per Spec
  05's `LocalFsBlobStore`. The web disables the button in dev
  with a small "dev only — open in terminal" hint, since
  browsers don't follow `file://` redirects.

### Orphan reaper

- **Lifespan-scoped task** (Spec 10 pattern): every 5 minutes,
  query `missions WHERE status = 'pending' AND created_at <
  now() - 1 hour`, mark them `cancelled` with reason `reaped`.
  Same query for missions in `phase = 'awaiting_approval'` with
  `created_at + 1 hour < now()`.
- **Idempotent**: the reaper acquires a row-level advisory lock
  per mission via Postgres `pg_advisory_xact_lock` so two
  reaper runs cannot double-cancel.
- **Logging**: `log.info("reaped %d missions", count)` per cycle
  when count > 0. Operators see this in structured logs.
- **What about `running` missions?** A mission in `running`
  with no recent task progress is *not* reaped automatically —
  detecting that requires per-task heartbeats and is outside
  Spec 14. Spec 15 may add it.

### Sidebar grouping update

- `MissionSidebar` from Spec 08 grouped by `running`, `pending`,
  `succeeded`, `failed`, `cancelled`. Spec 14 adds
  `awaiting_approval` as a sixth group, ordered after `pending`.
  Group derivation comes from `phase` when the mission is
  `running` and `phase = 'awaiting_approval'`; otherwise from
  `status`.
- Each row shows the cost on the right side in `font-mono
  tabular-nums`: `$0.012` or `?` if `cost_cents` is null on a
  terminal mission.

### What this spec does NOT do

- **Mid-render task interruption** — in-flight tasks still
  finish their network egress before honoring cancellation.
  Future spec may add a `cancel_token` plumbed through Scrapling
  + the LLM client.
- **Cost projection / per-token live counter during streaming**
  — only terminal cost is computed. Live cost requires
  per-tool-call Langfuse polls; deferred.
- **Bulk cancel from sidebar** — one mission at a time.
- **Snapshot mass-export** — single-snapshot download only.
- **Refund-style accounting (deduct from a budget)** — the cost
  is informational; no budget enforcement until paid plans
  exist.

References:
- `context/architecture.md` — Storage Model, **Invariants 4, 5,
  10**
- `context/code-standards.md` — FastAPI, Auth integration
- `context/ui-context.md` — Voice & Copy
- Skills: `fastapi`, `vercel-composition-patterns`,
  `pydantic-ai-dependency-injection`

## Implementation

### A. Cancellation endpoints — `apps/api/app/routes.py`

```python
@router.delete("/missions/{mission_id}", status_code=204)
async def cancel_mission(
    mission_id: UUID,
    user: RequireUser,
) -> Response:
    missions = MissionRepository()
    mission = await missions.get(mission_id)
    if mission is None:
        raise HTTPException(404, "not found")
    if mission.status not in {Status.PENDING, Status.RUNNING}:
        return Response(status_code=204, headers={"x-mission-state": mission.status.value})

    runner = active_runners.get(mission_id)
    if runner is not None:
        runner.request_cancellation()
        return Response(status_code=204, headers={"x-mission-state": "cancellation_pending"})

    # Runner not in this process (rare edge): mark cancelled directly.
    await missions.update_status(mission_id, Status.CANCELLED)
    return Response(status_code=204, headers={"x-mission-state": "cancelled"})


@router.delete("/missions/{mission_id}/tasks/{task_id}", status_code=204)
async def cancel_task(
    mission_id: UUID,
    task_id: UUID,
    user: RequireUser,
) -> Response:
    tasks_repo = TaskRepository()
    task = await tasks_repo.get(task_id)
    if task is None or task.mission_id != mission_id:
        raise HTTPException(404, "not found")
    if task.status not in {Status.PENDING, Status.RUNNING}:
        return Response(status_code=204)

    runner = active_runners.get(mission_id)
    if runner is not None:
        runner.cancel_task(task_id)
    else:
        # Rare edge: mark directly.
        await tasks_repo.update(task_id, status=Status.CANCELLED)
    return Response(status_code=204)
```

`active_runners` is a process-level dict mirroring
Spec 10's `_pending_approvals` pattern: `{mission_id: MissionRunner}`,
populated when `emitter.adopt_runner` runs and removed when the
runner's `run()` returns. `MissionRunner.cancel_task(task_id)`
sets a per-task flag; the existing `_run_task` body checks it
at the top before each step.

### B. `MissionRunner.cancel_task` — `apps/api/app/runner.py`

```python
class MissionRunner:
    def __init__(self, *, ...) -> None:
        # ... existing ...
        self._cancelled_task_ids: set[UUID] = set()

    def cancel_task(self, task_id: UUID) -> None:
        self._cancelled_task_ids.add(task_id)

    async def _run_task(self, task: Task) -> None:
        if task.id in self._cancelled_task_ids or self._cancellation_requested.is_set():
            await self._tasks_repo.update(task.id, status=Status.CANCELLED)
            await self._emit_task_end(task, status=Status.CANCELLED)
            return
        # ... existing task body ...
```

The check is also inserted just before each major step
(semaphore acquire, agent.run dispatch) so cancellation between
steps is honored without forcing a kill mid-call.

### C. Snapshot endpoint — `apps/api/app/routes.py`

```python
@router.get("/missions/{mission_id}/tasks/{task_id}/snapshot")
async def task_snapshot(
    mission_id: UUID,
    task_id: UUID,
    user: RequireUser,
) -> RedirectResponse:
    tasks_repo = TaskRepository()
    task = await tasks_repo.get(task_id)
    if task is None or task.mission_id != mission_id:
        raise HTTPException(404, "not found")
    if task.snapshot_key is None:
        raise HTTPException(404, "no snapshot")

    blob = get_blob_store()
    url = await blob.signed_url(task.snapshot_key, expires_in_seconds=3600)
    return RedirectResponse(url=url, status_code=302)
```

The 302 redirect uses the browser's standard navigation flow.
For local-fs dev, `LocalFsBlobStore.signed_url` returns a
`file://` URL; browsers refuse to follow these. The web's
`Download HTML` text-button checks the dev-mode env at render
time and renders the link as disabled with a hint.

### D. Cost computation — runner extension

`apps/api/app/observability.py` adds:

```python
async def fetch_mission_cost_cents(mission_id: UUID) -> int | None:
    """Query Langfuse for the trace's total cost in cents.
    Returns None if the trace is missing or the API is unreachable."""
    try:
        trace = await asyncio.to_thread(
            _client.fetch_trace, str(mission_id)
        )
    except Exception:
        log.exception("langfuse trace fetch failed", extra={"mission_id": str(mission_id)})
        return None

    cost_usd = trace.data.totalCost or 0.0
    return int(round(cost_usd * 100))
```

`MissionRunner._emit_mission_terminal` (the existing helper)
calls this and writes the result to the row before emitting
`done`:

```python
async def _emit_mission_terminal(self) -> None:
    final_status = self._compute_mission_status()
    cost = await fetch_mission_cost_cents(self._mission.id)
    await self._missions_repo.update_cost_cents(
        self._mission.id, cost or 0
    )
    await self._missions_repo.update_status(self._mission.id, final_status)
    await emitter.emit(SseEvent.model_validate({
        "type": "done",
        "content": {
            "mission_status": final_status_str(final_status),
            "cost_cents": cost or 0,
        },
        "mission_id": str(self._mission.id),
        "seq": 0,
    }))
```

`MissionRepository.update_cost_cents` is a one-line addition.

### E. Reaper loop — `apps/api/app/jobs/orphan_reaper.py`

```python
from __future__ import annotations

import asyncio
import logging

from datetime import datetime, timedelta, timezone

from app.persistence.repository import MissionRepository
from app.persistence.models import MissionPhase, Status


log = logging.getLogger(__name__)
_SWEEP_INTERVAL_S = 5 * 60
_TIMEOUT = timedelta(hours=1)


async def orphan_reaper_loop() -> None:
    repo = MissionRepository()
    while True:
        try:
            await asyncio.sleep(_SWEEP_INTERVAL_S)
            cutoff = datetime.now(timezone.utc) - _TIMEOUT
            count = await repo.reap_orphans(cutoff=cutoff)
            if count > 0:
                log.info("reaped %d orphan missions", count)
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("orphan reaper failed; continuing")
```

`MissionRepository.reap_orphans(cutoff)` runs:

```sql
UPDATE missions
SET status = 'cancelled',
    finished_at = now()
WHERE (
    (status = 'pending' AND created_at < :cutoff)
 OR (status = 'running' AND phase = 'awaiting_approval' AND created_at < :cutoff)
)
RETURNING id
```

Wired into the lifespan TaskGroup alongside `selector_sweep_loop`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with asyncio.TaskGroup() as tg:
        emitter._runners._tg = tg
        tg.create_task(selector_sweep_loop(), name="selector-sweep")
        tg.create_task(orphan_reaper_loop(), name="orphan-reaper")
        yield
```

### F. Web — Cancel mission button

`apps/web/widgets/mission-detail/index.tsx` (header):

```tsx
{mission?.status === "running" ? (
  <button
    type="button"
    onClick={onCancelMission}
    className="text-[11px] text-muted-foreground hover:text-state-error"
  >
    {t("mission", "cancelMission")}
  </button>
) : null}
```

`onCancelMission` calls
`fetch(`/api/missions/${id}`, { method: "DELETE" })`. After
cancel, the slide-over does not auto-close — the user sees
the cascading task cancellations in the lanes; close is
explicit.

### G. Web — Per-task cancel

`apps/web/features/run-mission/use-lane-focus.ts` — extend with
a `cancel()` action that calls
`fetch(`/api/missions/${missionId}/tasks/${taskId}`, { method: "DELETE" })`.

`apps/web/widgets/task-lane-stack/index.tsx` — replace the
existing `useShortcut("x", () => focus.unpin())` with
`useShortcut("x", () => focus.cancelOrUnpin())`. The combined
behavior:

- If the focused lane is in `pending` or `running`: cancel.
- If the focused lane is terminal: unpin.

Power users get the most useful action per state without a
mode switch.

The pin/unpin button moves to a small icon button in the row
body next to the chevron, since `X` is now overloaded.

### H. Web — Snapshot download button

`apps/web/widgets/task-lane-stack/result-preview.tsx`:

```tsx
{taskEnd.content.snapshot_key ? (
  <a
    href={`/api/missions/${missionId}/tasks/${taskId}/snapshot`}
    target="_blank"
    rel="noopener"
    className="mt-2 inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
  >
    {t("mission", "downloadHtml")}
    <ArrowRight className="h-3 w-3" aria-hidden />
  </a>
) : null}
```

The BFF route `/api/missions/[id]/tasks/[taskId]/snapshot/route.ts`
forwards the Clerk JWT to the api and follows the 302 to the
signed URL.

### I. Web — Sidebar awaiting-approval group + cost surface

`apps/web/widgets/mission-sidebar/index.tsx` — extend the
`GROUPS` const:

```tsx
const GROUPS = [
  "running",
  "awaiting_approval",
  "pending",
  "succeeded",
  "failed",
  "cancelled",
] as const;
```

`useMissions` derives the bucket: a row whose
`status === "running" && phase === "awaiting_approval"` lands in
the `awaiting_approval` bucket; otherwise the bucket is the
`status`.

`MissionRow` adds the cost on the right side:

```tsx
<span className="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground">
  {mission.cost_cents != null
    ? `$${(mission.cost_cents / 100).toFixed(3)}`
    : mission.status === "succeeded" || mission.status === "failed"
      ? "?"
      : ""}
</span>
```

### J. i18n keys (additions)

- `mission.cancelMission` — "Cancel mission"
- `mission.cancelTask` — "Cancel task"
- `mission.downloadHtml` — "Download HTML"
- `mission.unpin` — "Unpin"
- `mission.status_awaiting_approval` — "Awaiting approval"

### K. Tests

#### `apps/api/tests/test_cancellation_endpoints.py`

```python
@pytest.mark.asyncio
async def test_cancel_running_mission():
    # Start a mission with mocked runner; DELETE /missions/{id};
    # assert request_cancellation called; tasks transition to cancelled.

@pytest.mark.asyncio
async def test_cancel_idempotent():
    # DELETE twice on the same mission; second returns 204 with
    # x-mission-state header.

@pytest.mark.asyncio
async def test_cancel_task_only_pending():
    # Start a 3-task mission; cancel task 2 while running;
    # tasks 1, 3 finish normally.
```

#### `apps/api/tests/test_orphan_reaper.py`

```python
@pytest.mark.asyncio
async def test_reaper_marks_pending_older_than_1h(monkeypatch):
    # Seed a mission with created_at = 90min ago, status=pending.
    # Run reaper once; assert status=cancelled.

@pytest.mark.asyncio
async def test_reaper_marks_awaiting_approval_older_than_1h():
    # Seed a description-mode mission parked in awaiting_approval.
    # Run reaper once; assert status=cancelled.

@pytest.mark.asyncio
async def test_reaper_skips_recent():
    # Seed a mission 30min old; reaper does not touch it.
```

#### `apps/api/tests/test_snapshot_endpoint.py`

```python
@pytest.mark.asyncio
async def test_returns_signed_url_redirect():
    # Seed task with snapshot_key. GET endpoint with auth;
    # expect 302; Location header points at a signed URL.

@pytest.mark.asyncio
async def test_404_when_no_snapshot():
    # Seed task without snapshot_key. Expect 404.

@pytest.mark.asyncio
async def test_404_for_other_user():
    # Test cross-tenant isolation via RLS.
```

#### `apps/api/tests/test_cost_writeback.py`

```python
@pytest.mark.asyncio
async def test_terminal_writes_cost_cents(monkeypatch):
    # Mock Langfuse trace fetch to return totalCost=0.012.
    # Run runner to terminal; assert missions.cost_cents == 1.

@pytest.mark.asyncio
async def test_cost_failure_leaves_zero(monkeypatch):
    # Mock Langfuse to raise; runner still emits done; cost_cents == 0.
```

#### Web tests

- `apps/web/widgets/mission-detail/cancel-mission.test.tsx` —
  button visible only when running; click triggers DELETE;
  loading state during request.
- `apps/web/widgets/mission-sidebar/sidebar.test.tsx` — new
  awaiting_approval bucket renders correctly; cost displays.
- `apps/web/widgets/task-lane-stack/result-preview-snapshot.test.tsx`
  — download link renders when `snapshot_key` present; absent
  otherwise.

### L. Order of operations

1. `MissionRunner.cancel_task` + per-task check inside
   `_run_task`.
2. `active_runners` registry on the emitter.
3. `DELETE /missions/{id}` and `DELETE /missions/{id}/tasks/{task_id}`
   endpoints.
4. `fetch_mission_cost_cents` helper in
   `app/observability.py`.
5. `MissionRepository.update_cost_cents` and
   `reap_orphans` methods.
6. `app/jobs/orphan_reaper.py` + lifespan wiring.
7. `GET /missions/{id}/tasks/{task_id}/snapshot` endpoint and
   the BFF forwarding route.
8. Web: cancel mission button in slide-over header; cancel
   task on `X`; pin/unpin icon button.
9. Web: download HTML link in result preview.
10. Web: sidebar awaiting_approval bucket + cost surface.
11. Add the 5 i18n keys.
12. Run the verification block.

## Out of Scope

- **Mid-render task interruption** — in-flight tasks still
  finish their current network egress; cancellation only
  affects pending or between-step states.
- **Live per-token cost counter during streaming** — terminal
  cost only.
- **Bulk cancel from the sidebar** — one mission at a time.
- **Snapshot mass-export / archive download** — single-snapshot
  retrieval only.
- **`cost_cents` reconciliation if Langfuse fetch fails** —
  Spec 15 may add a retry sweep.
- **Admin endpoint to manually evict / reap** — out of scope.

## Files

### Create

- `apps/api/app/jobs/orphan_reaper.py`
- `apps/api/tests/test_cancellation_endpoints.py`
- `apps/api/tests/test_orphan_reaper.py`
- `apps/api/tests/test_snapshot_endpoint.py`
- `apps/api/tests/test_cost_writeback.py`
- `apps/web/app/api/missions/[id]/tasks/[taskId]/snapshot/route.ts`
- `apps/web/widgets/mission-detail/cancel-mission.test.tsx`
- `apps/web/widgets/mission-sidebar/sidebar.test.tsx`
- `apps/web/widgets/task-lane-stack/result-preview-snapshot.test.tsx`

### Edit

- `apps/api/app/routes.py` — add 3 endpoints
- `apps/api/app/runner.py` — `MissionRunner.cancel_task`,
  per-task check, terminal cost write-back; `active_runners`
  registry
- `apps/api/app/observability.py` — `fetch_mission_cost_cents`
- `apps/api/app/persistence/repository.py` — `update_cost_cents`,
  `reap_orphans`
- `apps/api/app/main.py` — register `orphan_reaper_loop` in
  lifespan
- `apps/api/app/sse.py` — track `active_runners` on adopt /
  release
- `apps/web/widgets/mission-detail/index.tsx` — cancel button
- `apps/web/widgets/task-lane-stack/result-preview.tsx` —
  download link
- `apps/web/widgets/task-lane-stack/index.tsx` — `X` shortcut
  changes meaning
- `apps/web/widgets/task-lane-stack/task-lane-row.tsx` — pin/
  unpin icon button
- `apps/web/widgets/mission-sidebar/index.tsx` — new bucket;
  `MissionRow` cost rendering
- `apps/web/features/run-mission/use-lane-focus.ts` —
  `cancelOrUnpin` action
- `apps/web/features/run-mission/use-missions.ts` — derive
  `awaiting_approval` bucket
- `apps/web/shared/i18n/keys/en.ts` — append 5 new keys

### Protected (do not touch)

- `apps/api/app/security.py`
- Past alembic migrations
- `packages/sse-protocol/generated/**`
- `apps/web/components/ui/*`
- All previous protected files

## Verification

Run from the repo root.

- `cd apps/api && uv sync` is a no-op.
- `turbo run lint` exits 0.
- `turbo run typecheck` exits 0.
- `turbo run test` exits 0.
- `turbo run build` exits 0.

Manual:

- Submit a 5-URL mission. After lane 2 starts, click `Cancel
  mission` in the slide-over header. Within ~1s the remaining
  pending tasks transition to `cancelled` in their lane chips.
  In-flight tasks finish normally.
- Submit another mission. Focus lane 2 with K; press `X`. Lane
  2 transitions to `cancelled`. Lane 1, 3, 4 continue.
- Mission terminates. Sidebar entry shows `$0.012` (or whatever
  Langfuse returns).
- Click `Download HTML` on lane 1's result preview. Browser
  opens the gzipped snapshot in a new tab.
- Submit a description-mode mission; close the slide-over
  during awaiting_approval. After 1 hour and 5 minutes (or
  shorter via the dev `_TIMEOUT` override), the mission shows
  in the sidebar's `cancelled` group.
- Cancel an already-cancelled mission via curl: returns 204
  with `x-mission-state: cancellation_pending` (still active
  runner) or `x-mission-state: cancelled` (already terminal).

## Done when

- [ ] Every Verification line passes.
- [ ] No invariant in `context/architecture.md` violated.
  Specifically: invariants 4 (single SSE queue), 5 (terminal
  events still fire on cancel), 7 (DB writes precede SSE
  emission), and 10 (mission status checks on each task body).
- [ ] `apps/api/app/security.py` was not edited.
- [ ] `i18n-keeper` agent flags zero hardcoded English strings.
- [ ] `fsd-architect` agent flags zero layer violations.
- [ ] `context/progress-tracker.md` updated: Spec 14 to
  "Completed"; Spec 15 to "In Progress".
- [ ] `scrape-pipeline-doctor` agent run on `apps/api/**`
  confirms invariants 4, 5, 7, 10 still hold post-cancel.
- [ ] `sse-streaming-reviewer` agent run on the cancellation
  event paths finds zero violations against the Spec 06
  contract.
- [ ] `llm-cost-guard` agent run on
  `apps/api/app/observability.py` (the new
  `fetch_mission_cost_cents`) and the new `DELETE` /
  `/snapshot` endpoints confirms rate-limit coverage and that
  Langfuse failures degrade gracefully without unbounded
  retries.
- [ ] `code-reviewer` agent run on the chunk produces
  `CODE_REVIEW.md` with `Verdict: Approve`.
- [ ] `simplify` skill review on the diff returns no actionable
  findings.

## Scrape reliability note

This spec closes the operational loop:

1. **Cancellation propagates correctly.** The TaskGroup mechanic
   from Spec 10 was load-bearing for invariant 3; this spec
   exposes it to users without violating any guarantee. In-
   flight tasks still finish their current network call —
   the architecture's pending-cancelled / in-flight-finish rule
   is honored.
2. **Stuck missions auto-clean.** A mission parked in pending
   for >1h cannot keep a task slot occupied indefinitely. The
   reaper marks them cancelled within 5-65 minutes of the
   timeout. Spec 12's awaiting-approval missions are
   particularly susceptible — the reaper handles them on the
   same schedule.
3. **Cost is observable.** Sidebar shows per-mission cost in
   USD; users can budget. Langfuse failures degrade gracefully
   (cost shows `?`) without blocking the mission.
4. **Snapshot retrieval is auditable.** A user who wants to
   inspect what was actually scraped can download the gzipped
   HTML behind a 1-hour signed URL. Useful for debugging
   parser drift, copyright disputes, and "did the scrape really
   capture page X" questions.

What remains: Spec 15's hardening + e2e + production deploy.
