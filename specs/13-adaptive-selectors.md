# 13 — adaptive-selectors

## Goal

Wire Scrapling's adaptive selector feature so a selector saved on
domain X during run N is reused on the same domain during run N+1
even if the site's DOM has shifted. Persist saved selectors to
the `saved_selectors` table (Spec 05 already provisioned), front
the table with a 1k-entry in-process LRU cache, evict by TTL
(30 days) and consecutive-failure count (≥3). Emit a
`selector_recovered` SSE event whenever an adaptive match
succeeds; render a small "selectors recovered N times" indicator
inline in the task lane. After this spec, invariant 8
(`adaptive selectors namespace by (domain, selector_purpose)`)
is enforced both in code and in the database's covering index.

## Dependencies

- `specs/05` — `saved_selectors` table, `SelectorRepository`,
  covering unique index on `(domain, purpose)`
- `specs/06` — `selector_recovered` SSE event type already
  defined in the schema
- `specs/07` — Crawl4AI `MarkdownExtractor` is the consumer of
  the selected element
- `specs/09` — three tier tools, `persist_snapshot` helper
- `specs/10` — `MissionRunner`, lifespan-scoped TaskGroup
- `specs/11` — `TaskLaneRow` renderer (new selector indicator
  attaches inline in the lane body)
- The Spec 13 research note on Scrapling's adaptive API and its
  six gaps Autumn must fill

## Design Decisions

### What gets cached

- **One purpose for now: `MAIN_CONTENT`.** Every successful
  fetch (HTTP, Stealth, Dynamic) runs the page's HTML through a
  shared `select_main_content(page, domain)` helper that:
  1. Tries Scrapling's adaptive `.css('main, article, [role="main"]', identifier=f'{purpose}', auto_save=True, adaptive=True, percentage=70)`
  2. Falls back to Crawl4AI's heuristic if no element matches
  3. Hands the selected element's HTML to Crawl4AI for markdown
     conversion
- The `purpose` enum starts as a one-member literal in the api;
  later specs add new purposes when a need actually exists.
  No speculative taxonomy.

### Tier scope

- **All three tiers run `select_main_content`** before the
  Crawl4AI extraction step. The helper sits between the fetcher
  and the markdown extractor in `app/tools/_select.py`. Uniform
  extraction path for HTTP, Stealth, and Dynamic.
- The current Crawl4AI integration in `app/extract/__init__.py`
  takes raw HTML and returns markdown. Spec 13 changes the call
  shape: the extractor now receives the **scoped** HTML (the
  inner HTML of the selected element), not the whole page. If
  no main element is found, the full body is passed (no
  regression on edge cases).

### Storage backend — the monkey-patch pattern

- Scrapling's fetchers do not expose a `storage=` kwarg. The
  research recommends post-fetch monkey-patching:
  `page._storage = PostgresStorage(repo, url=str(page.url))`.
- A custom `PostgresStorage` subclasses `StorageSystemMixin`,
  decorated with `@lru_cache(1, typed=True)` per parser.py's
  enforcement. It implements `save(element, identifier)` and
  `retrieve(identifier)` against `SelectorRepository`. The
  in-process LRU sits in front of `find()`, write-through to
  the DB on `upsert()`.
- `PostgresStorage.retrieve` is instrumented to emit a "pending
  recovery" marker that the call site reads to know an adaptive
  match was about to be attempted. The call site emits the
  `selector_recovered` SSE event on successful match.

### LRU cache + repository extensions

- **In-process LRU**: `cachetools.LRUCache(maxsize=1000)` keyed
  on `(domain, purpose)`, value is the cached payload dict.
  Lives at `app/persistence/selector_cache.py`. Read-through:
  cache miss → repo find → cache put. Write-through: every
  `upsert` invalidates and re-populates.
- **Repository extensions** (`SelectorRepository`):
  - `find(domain, purpose) -> SavedSelector | None` —
    LRU-fronted read.
  - `upsert(domain, purpose, payload)` — write-through; resets
    `failure_count` to 0; bumps `last_used_at`.
  - `bump_hit_count(domain, purpose)` — increment on successful
    adaptive match.
  - `bump_failure_count(domain, purpose) -> int` — increment;
    return new value. Caller deletes if ≥3.
  - `delete(domain, purpose)` — cache + DB removal.
  - `evict_older_than(days: int) -> int` — sweep; deletes rows
    where `last_used_at < now - days`; returns count.
- `failure_count` is a new column on `saved_selectors`.
  Migration `0003_add_failure_count`.

### Eviction policy (three layers)

1. **LRU 1k**: in-process; protects memory. Eviction is silent.
2. **TTL 30 days**: a sweep coroutine runs every 6 hours from
   the lifespan TaskGroup (Spec 10's pattern), deleting rows
   where `last_used_at < now - 30d`. Logs the count.
3. **Failure-count ≥ 3**: every `select_main_content` call that
   uses a saved selector and gets zero matches calls
   `bump_failure_count`; if the new count is ≥ 3, the row is
   deleted. Self-heals when sites redesign.

### `selector_recovered` event emission

- Spec 06's schema defines the event with `domain`, `purpose`,
  `hit_count`. The emission point is inside the call-site
  wrapper around `page.css(..., adaptive=True)`:

  ```
  hits = page.css(...)
  if not hits:
      hits = page.css(..., adaptive=True)
      if hits:
          new_hit_count = repo.bump_hit_count(domain, purpose)
          await emitter.emit(SseEvent({type: "selector_recovered",
              content: {domain, purpose, hit_count: new_hit_count},
              mission_id, task_id, seq: 0}))
  ```

- The event carries `task_id` (it happens inside a task body),
  so the web's `TaskLaneStack` from Spec 11 attributes it to
  the correct lane.

### Web rendering — small indicator chip

- `TaskLaneRow` from Spec 11 gets one new piece of state:
  `selectorRecoveryCount` (int). Driven by counting
  `selector_recovered` events for the lane in `useTaskLanes`.
- When `selectorRecoveryCount > 0`, a small chip renders in
  the lane's expanded body next to the tool chips:

  ```html
  <span class="inline-flex h-5 items-center gap-1 rounded
               border border-border/50 bg-muted/40 px-1.5
               text-[11px] font-mono text-muted-foreground">
    <Sparkle class="h-3 w-3" />
    {t("mission","selectorsRecovered",{count: N})}
  </span>
  ```

- The chip uses i18n plural API (`count`) to resolve to
  "selector recovered" / "selectors recovered" by N. No
  marketing flourish; sentence-case copy per Voice & Copy.

### What this spec does NOT do

- **Multi-purpose taxonomy** (PAGINATION, ARTICLE_BODY, etc.) —
  added when a future spec actually needs it.
- **Cross-user / cross-tenant selector sharing config** — selectors
  are deployment-scoped per `architecture.md` decision; revisit
  per `progress-tracker.md` Open Question 5.
- **Selector quality metrics dashboard** — recovery counts live
  in the row and Langfuse traces; UI dashboard is post-MVP.
- **Per-mission "force fresh selectors" override** — the agent
  cannot instruct Scrapling to skip the cache. If a user wants
  to force fresh, manually delete the row via a future admin UI.

References:
- `context/architecture.md` — Storage Model (saved_selectors,
  LRU 1k), **Invariant 8**
- `context/code-standards.md` — Python (async, repository),
  Data and Storage
- `context/ui-context.md` — Voice & Copy
- Spec 13 research notes on Scrapling adaptive (six gaps,
  three code snippets)
- Skills: `pydantic-models-py`, `fastapi`,
  `vercel-composition-patterns`

## Implementation

### A. Migration — `apps/api/alembic/versions/0003_*`

```python
def upgrade() -> None:
    op.add_column(
        "saved_selectors",
        sa.Column(
            "failure_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("saved_selectors", "failure_count")
```

Update `app/persistence/models.py`:

```python
class SavedSelector(SQLModel, table=True):
    __tablename__ = "saved_selectors"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    domain: str = Field(max_length=253, index=True)
    purpose: str = Field(max_length=64, index=True)
    payload: dict = Field(sa_column=Column(JSONB, nullable=False))
    hit_count: int = Field(default=0)
    failure_count: int = Field(default=0)
    last_used_at: datetime = Field(
        sa_column_kwargs={"server_default": text("now()")},
    )

    __table_args__ = (
        Index(
            "ix_saved_selectors_domain_purpose",
            "domain",
            "purpose",
            unique=True,
        ),
    )
```

### B. Purpose enum — `apps/api/app/tools/_purposes.py`

```python
from __future__ import annotations

from enum import StrEnum


class SelectorPurpose(StrEnum):
    MAIN_CONTENT = "main_content"
```

A single member today. Adding new purposes is a one-line change
plus the call sites that use them.

### C. LRU-fronted repository extensions

#### `apps/api/app/persistence/selector_cache.py`

```python
from __future__ import annotations

from cachetools import LRUCache


# 1000 entries; per the research, ~1-2 MB at saturation.
_cache: LRUCache[tuple[str, str], dict] = LRUCache(maxsize=1000)


def cache_get(domain: str, purpose: str) -> dict | None:
    return _cache.get((domain, purpose))


def cache_put(domain: str, purpose: str, payload: dict) -> None:
    _cache[(domain, purpose)] = payload


def cache_evict(domain: str, purpose: str) -> None:
    _cache.pop((domain, purpose), None)
```

`cachetools` is added to `apps/api/pyproject.toml`. Process-local
state; Spec 14's reaper handles cross-process drift if
deployment ever scales horizontally.

#### `SelectorRepository` extensions —
`apps/api/app/persistence/repository.py`

```python
class SelectorRepository:
    async def find(self, domain: str, purpose: str) -> SavedSelector | None:
        cached = cache_get(domain, purpose)
        if cached is not None:
            # Build a transient SavedSelector from cache for callers that
            # treat the repository's contract as the source of truth.
            return SavedSelector(
                id=uuid.UUID(cached["id"]),
                domain=domain,
                purpose=purpose,
                payload=cached["payload"],
                hit_count=cached["hit_count"],
                failure_count=cached["failure_count"],
                last_used_at=datetime.fromisoformat(cached["last_used_at"]),
            )

        async with transaction() as session:
            stmt = select(SavedSelector).where(
                SavedSelector.domain == domain,
                SavedSelector.purpose == purpose,
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                return None
            cache_put(domain, purpose, _to_cache_dict(row))
            return row

    async def upsert(
        self, *, domain: str, purpose: str, payload: dict
    ) -> SavedSelector:
        async with transaction() as session:
            existing = await session.execute(
                select(SavedSelector).where(
                    SavedSelector.domain == domain,
                    SavedSelector.purpose == purpose,
                )
            )
            row = existing.scalars().first()
            if row is None:
                row = SavedSelector(
                    domain=domain, purpose=purpose, payload=payload
                )
                session.add(row)
            else:
                row.payload = payload
                row.failure_count = 0
                row.last_used_at = datetime.now(timezone.utc)
            await session.flush()
            cache_put(domain, purpose, _to_cache_dict(row))
            return row

    async def bump_hit_count(self, domain: str, purpose: str) -> int:
        async with transaction() as session:
            stmt = (
                update(SavedSelector)
                .where(
                    SavedSelector.domain == domain,
                    SavedSelector.purpose == purpose,
                )
                .values(
                    hit_count=SavedSelector.hit_count + 1,
                    last_used_at=datetime.now(timezone.utc),
                )
                .returning(SavedSelector)
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                return 0
            cache_put(domain, purpose, _to_cache_dict(row))
            return row.hit_count

    async def bump_failure_count(self, domain: str, purpose: str) -> int:
        async with transaction() as session:
            stmt = (
                update(SavedSelector)
                .where(
                    SavedSelector.domain == domain,
                    SavedSelector.purpose == purpose,
                )
                .values(failure_count=SavedSelector.failure_count + 1)
                .returning(SavedSelector)
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                return 0
            if row.failure_count >= 3:
                await session.delete(row)
                cache_evict(domain, purpose)
                return row.failure_count
            cache_put(domain, purpose, _to_cache_dict(row))
            return row.failure_count

    async def delete(self, domain: str, purpose: str) -> None:
        async with transaction() as session:
            stmt = sa_delete(SavedSelector).where(
                SavedSelector.domain == domain,
                SavedSelector.purpose == purpose,
            )
            await session.execute(stmt)
        cache_evict(domain, purpose)

    async def evict_older_than(self, *, days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with transaction() as session:
            stmt = sa_delete(SavedSelector).where(
                SavedSelector.last_used_at < cutoff
            ).returning(SavedSelector.domain, SavedSelector.purpose)
            result = await session.execute(stmt)
            evicted = list(result.fetchall())
        for domain, purpose in evicted:
            cache_evict(domain, purpose)
        return len(evicted)


def _to_cache_dict(row: SavedSelector) -> dict:
    return {
        "id": str(row.id),
        "payload": row.payload,
        "hit_count": row.hit_count,
        "failure_count": row.failure_count,
        "last_used_at": row.last_used_at.isoformat(),
    }
```

The `transaction()` context manager from Spec 05 is RLS-aware,
but `saved_selectors` has no RLS (deployment-scoped per
architecture). The transaction still binds `app.user_id` from
the context, but the table's policies don't reference it.

### D. PostgresStorage backend — `apps/api/app/tools/_storage.py`

```python
from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from scrapling.core.storage import StorageSystemMixin
from scrapling.core.utils import _StorageTools

from app.persistence.repository import SelectorRepository


@lru_cache(1, typed=True)
class PostgresStorage(StorageSystemMixin):
    """Bridges Scrapling's element-storage protocol to our async
    SelectorRepository. The lru_cache(1) decorator is required by
    Scrapling's parser.py:175 — without it, parser raises."""

    def __init__(
        self,
        repo: SelectorRepository,
        url: str | None = None,
        purpose: str = "main_content",
    ) -> None:
        super().__init__(url)
        self._repo = repo
        self._purpose = purpose
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending_recovery: tuple[str, str] | None = None

    def save(self, element: Any, identifier: str) -> None:
        """Scrapling calls this synchronously from inside .css()."""
        domain = self._get_base_url()
        data = _StorageTools.element_to_dict(element)
        # Bridge to async by scheduling on the active loop. The runner's
        # task is awaiting page.css(); we run upsert as a task and
        # block briefly via asyncio.run_coroutine_threadsafe equivalent.
        loop = self._loop or asyncio.get_running_loop()
        loop.create_task(
            self._repo.upsert(domain=domain, purpose=identifier, payload=data),
            name=f"selector-save:{domain}:{identifier}",
        )
        # No await: fire-and-forget, write-through eventual consistency.
        # The next task on the same domain reads the cached value if the
        # write completed; otherwise it does a fresh fetch and overwrites.

    def retrieve(self, identifier: str) -> dict | None:
        """Scrapling calls this synchronously when adaptive=True falls back."""
        domain = self._get_base_url()
        # Synchronous read against the in-process LRU only — never blocks
        # on Postgres in the hot path. Cache misses fall through to a
        # synchronous bump_failure_count after the no-match return.
        from app.persistence.selector_cache import cache_get
        cached = cache_get(domain, identifier)
        if cached is None:
            return None
        # Mark recovery pending; emitter-side reads this after .css() returns.
        self._pending_recovery = (domain, identifier)
        return cached["payload"]
```

Notes on the `save` path's fire-and-forget:

- `Scrapling`'s `.css()` is a synchronous Python method. `save`
  must therefore be sync. We schedule the async upsert on the
  running loop without awaiting it.
- This is acceptable because:
  - The next read on the same `(domain, purpose)` reads the
    in-process LRU first; if the write hasn't landed yet, the
    cache miss falls back to a fresh fetch and overwrites.
  - Worst case is one redundant fetch per slow-write race;
    correctness is preserved.
  - The `lifespan`-scoped TaskGroup adopts the upsert task so
    invariant 3 holds.
- The `retrieve` path reads the **cache only**, never the DB —
  hot path stays synchronous and fast. Cache misses behave as
  "no saved selector exists"; the call site falls back to
  Crawl4AI's heuristic. The DB read happens elsewhere (the
  pre-warm step described in section E).

### E. The `select_main_content` helper —
`apps/api/app/tools/_select.py`

```python
from __future__ import annotations

import logging
from uuid import UUID

from autumn_sse_protocol import SseEvent

from app.persistence.repository import SelectorRepository
from app.persistence.selector_cache import cache_put
from app.sse import emitter
from app.tools._purposes import SelectorPurpose
from app.tools._storage import PostgresStorage


log = logging.getLogger(__name__)


_MAIN_CONTENT_SELECTOR = (
    'main, [role="main"], article, '
    "div.main, div#main, div.content, div#content"
)


async def select_main_content(
    *,
    page,  # Scrapling's Selector / Response
    domain: str,
    mission_id: UUID,
    task_id: UUID,
    repo: SelectorRepository,
) -> str:
    """Return the inner HTML of the page's main-content region. Uses
    Scrapling's adaptive selector if available; falls back to the page's
    full body. Emits `selector_recovered` on a successful adaptive match.

    Honors invariant 8: selectors are namespaced by `(domain, purpose)`.
    """
    purpose = SelectorPurpose.MAIN_CONTENT.value

    # Pre-warm the LRU from Postgres so PostgresStorage.retrieve hits
    # the cache synchronously inside Scrapling's .css() call.
    existing = await repo.find(domain=domain, purpose=purpose)
    if existing is not None:
        cache_put(domain, purpose, {
            "id": str(existing.id),
            "payload": existing.payload,
            "hit_count": existing.hit_count,
            "failure_count": existing.failure_count,
            "last_used_at": existing.last_used_at.isoformat(),
        })

    # Monkey-patch Scrapling's storage on this page only.
    storage = PostgresStorage(repo=repo, url=str(page.url), purpose=purpose)
    page._storage = storage  # ruff: allow-private  scrapling exposes this
    type(page).adaptive = True  # class attr, idempotent

    # First try without adaptive (saves on first run).
    hits = page.css(
        _MAIN_CONTENT_SELECTOR,
        identifier=purpose,
        auto_save=True,
    )
    recovered_via_adaptive = False
    if not hits and existing is not None:
        # Existing selector saved; try adaptive relocation.
        hits = page.css(
            _MAIN_CONTENT_SELECTOR,
            identifier=purpose,
            auto_save=True,
            adaptive=True,
            percentage=70,
        )
        if hits:
            recovered_via_adaptive = True
        else:
            new_failure_count = await repo.bump_failure_count(
                domain=domain, purpose=purpose
            )
            log.info(
                "adaptive selector failed",
                extra={
                    "domain": domain,
                    "purpose": purpose,
                    "failure_count": new_failure_count,
                },
            )

    # Emit selector_recovered if the recovery path produced a hit.
    if recovered_via_adaptive:
        new_hit_count = await repo.bump_hit_count(
            domain=domain, purpose=purpose
        )
        await emitter.emit(
            SseEvent.model_validate(
                {
                    "type": "selector_recovered",
                    "content": {
                        "domain": domain,
                        "purpose": purpose,
                        "hit_count": new_hit_count,
                    },
                    "mission_id": str(mission_id),
                    "task_id": str(task_id),
                    "seq": 0,
                }
            )
        )

    # Return the scoped HTML, or the full body if no main element matched.
    if hits:
        first = hits[0]
        return first.html_content if hasattr(first, "html_content") else str(first)
    return page.body.decode("utf-8", errors="replace") if isinstance(page.body, bytes) else str(page.body)
```

The `_MAIN_CONTENT_SELECTOR` is a comma-list of common main-
content patterns. Scrapling's `.css()` with adaptive matches the
first hit on a normal page; the adaptive fallback re-locates by
similarity when the saved element's tag/attrs/text drift.

### F. Tier tools wire `select_main_content`

Each tier tool calls the helper between fetch and Crawl4AI
extraction. The change in each is a 4-line insertion plus an
extra constructor param.

#### `apps/api/app/tools/http.py` — partial diff

```python
from urllib.parse import urlparse

from app.persistence.repository import SelectorRepository
from app.tools._select import select_main_content


@observe(name="tool.scrape_http")
async def scrape_http(deps: HttpToolDeps, args: HttpScrapeArgs) -> HttpScrapeResult:
    assert_safe_url(args.url)
    await assert_robots_allows(args.url, robots_override=deps.robots_override)

    start = perf_counter()
    async with current_mission_semaphores().http_slot():
        fetcher = AsyncFetcher()
        page = await fetcher.get(args.url, stealthy_headers=True, follow_redirects=True)
        if page.status >= 400:
            # ... existing WAF detection branch unchanged ...
            ...

    domain = urlparse(str(page.url)).hostname or ""
    repo = SelectorRepository()
    main_html = await select_main_content(
        page=page,
        domain=domain,
        mission_id=deps.mission_id,
        task_id=deps.task_id,
        repo=repo,
    )

    extractor = MarkdownExtractor()
    extracted = await extractor.extract(html=main_html.encode("utf-8"), source_url=str(page.url))
    ...
```

`MarkdownExtractor.extract` accepts `bytes`; we re-encode the
scoped HTML on the way in. The same insertion happens in
`stealth.py` and `dynamic.py` after their respective WAF-detection
branches.

### G. Sweep job for TTL eviction —
`apps/api/app/jobs/selector_sweep.py`

```python
from __future__ import annotations

import asyncio
import logging

from app.persistence.repository import SelectorRepository


log = logging.getLogger(__name__)
_SWEEP_INTERVAL_S = 6 * 3600  # 6 hours
_TTL_DAYS = 30


async def selector_sweep_loop() -> None:
    """Run every 6 hours; evict saved selectors older than 30 days."""
    repo = SelectorRepository()
    while True:
        try:
            await asyncio.sleep(_SWEEP_INTERVAL_S)
            count = await repo.evict_older_than(days=_TTL_DAYS)
            if count > 0:
                log.info("selector sweep evicted %d rows", count)
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("selector sweep failed; continuing")
```

Wired into `app/main.py`'s lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with asyncio.TaskGroup() as tg:
        emitter._runners._tg = tg
        tg.create_task(selector_sweep_loop(), name="selector-sweep")
        yield
```

The sweep task lives for the process lifetime; cancellation on
shutdown is structured via the TaskGroup.

### H. Web — `selector_recovered` rendering

#### `useTaskLanes` extension (`apps/web/features/run-mission/use-task-lanes.ts`)

Add `selectorRecoveryCount` to `TaskLane`. Inside the event
projection loop:

```ts
case "selector_recovered":
  lane.selectorRecoveryCount = (lane.selectorRecoveryCount ?? 0) + 1;
  break;
```

Update the `TaskLane` interface:

```ts
export interface TaskLane {
  // ... existing fields ...
  selectorRecoveryCount?: number;
}
```

#### `TaskLaneRow` chip rendering
(`apps/web/widgets/task-lane-stack/task-lane-row.tsx`)

In the expanded body, alongside the tool chips:

```tsx
{lane.selectorRecoveryCount && lane.selectorRecoveryCount > 0 ? (
  <SelectorRecoveryChip count={lane.selectorRecoveryCount} />
) : null}
```

#### `SelectorRecoveryChip` —
`apps/web/widgets/task-lane-stack/selector-recovery-chip.tsx`

```tsx
"use client";

import { Sparkle } from "lucide-react";
import { useT } from "@/shared/i18n";


export function SelectorRecoveryChip({ count }: { count: number }) {
  const t = useT();
  return (
    <span
      className="inline-flex h-5 items-center gap-1 rounded border border-border/50 bg-muted/40 px-1.5 text-[11px] font-mono text-muted-foreground"
      title={t("mission", "selectorsRecoveredHint")}
    >
      <Sparkle className="h-3 w-3" aria-hidden />
      {t("mission", "selectorsRecovered", { count })}
    </span>
  );
}
```

i18n keys:
- `mission.selectorsRecovered` (plural via `count`):
  `_one` → `1 selector recovered`,
  `_other` → `{count} selectors recovered`
- `mission.selectorsRecoveredHint` —
  "Saved selectors matched after the site's DOM shifted."

### I. Tests

#### `apps/api/tests/test_selector_repository.py`

```python
@pytest.mark.asyncio
async def test_lru_cache_round_trip():
    repo = SelectorRepository()
    await repo.upsert(domain="example.com", purpose="main_content", payload={"tag": "main"})

    # Cache hit on second find.
    first = await repo.find("example.com", "main_content")
    second = await repo.find("example.com", "main_content")
    assert first.id == second.id


@pytest.mark.asyncio
async def test_failure_count_evicts_at_threshold():
    repo = SelectorRepository()
    await repo.upsert(domain="example.com", purpose="main_content", payload={"tag": "main"})

    assert await repo.bump_failure_count("example.com", "main_content") == 1
    assert await repo.bump_failure_count("example.com", "main_content") == 2
    assert await repo.bump_failure_count("example.com", "main_content") >= 3
    # Now deleted; find returns None.
    assert await repo.find("example.com", "main_content") is None


@pytest.mark.asyncio
async def test_evict_older_than():
    # Seed a row with last_used_at 31 days ago via direct SQL,
    # then call evict_older_than(days=30).
    ...
```

#### `apps/api/tests/test_select_main_content.py`

```python
@pytest.mark.asyncio
async def test_first_run_saves_selector(monkeypatch):
    # Fixture: mock Scrapling page with a valid <main> element.
    # Assert: repo.upsert called once; no selector_recovered event emitted.
    ...


@pytest.mark.asyncio
async def test_second_run_with_drifted_dom_recovers(monkeypatch):
    # Seed repo with a saved selector for example.com/main_content.
    # Build a page whose <main> tag has been renamed to <article>.
    # Assert: hits is non-empty (adaptive fallback succeeded);
    # selector_recovered event emitted with hit_count >= 1.
    ...


@pytest.mark.asyncio
async def test_third_consecutive_failure_evicts(monkeypatch):
    # Seed repo. Run three failed adaptive matches.
    # Assert: row deleted after third failure.
    ...
```

#### `apps/web/features/run-mission/use-task-lanes.test.ts`

Add a case:

```ts
test("counts selector_recovered events per lane", () => {
  const events: SseEvent[] = [
    taskStart(taskA, "https://x/"),
    selectorRecovered(taskA),
    selectorRecovered(taskA),
    taskStart(taskB, "https://y/"),
    selectorRecovered(taskB),
  ];
  const { result } = renderHook(() => useTaskLanes("m1", events));
  expect(result.current[0].selectorRecoveryCount).toBe(2);
  expect(result.current[1].selectorRecoveryCount).toBe(1);
});
```

#### `apps/web/widgets/task-lane-stack/selector-recovery-chip.test.tsx`

Renders the singular form when `count=1`; plural when `count>1`;
hint tooltip on hover.

### J. Order of operations

1. `cd apps/api && uv add cachetools`. Run alembic migration
   `0003`.
2. Update `app/persistence/models.py` with the `failure_count`
   field.
3. Build `app/persistence/selector_cache.py` (LRU helpers).
4. Extend `SelectorRepository` with the five new methods.
5. Build `app/tools/_purposes.py` (single-member enum).
6. Build `app/tools/_storage.py` (`PostgresStorage`).
7. Build `app/tools/_select.py` (`select_main_content`).
8. Wire `select_main_content` into `tools/http.py`,
   `tools/stealth.py`, `tools/dynamic.py`.
9. Update `app/extract/__init__.py` to accept scoped HTML
   (no API change; the bytes are just smaller now).
10. Build `app/jobs/selector_sweep.py`. Wire into the lifespan
    TaskGroup.
11. Web: add `selectorRecoveryCount` to `TaskLane` projection;
    build `SelectorRecoveryChip`; render in `TaskLaneRow`.
12. Add the 2 i18n keys.
13. Run the verification block.

## Out of Scope

- **Multi-purpose taxonomy** — single `MAIN_CONTENT` purpose for
  now.
- **Cross-tenant selector visibility config** — deployment-scoped
  per architecture decision.
- **UI for browsing / deleting saved selectors** — admin
  surface, post-MVP.
- **Selector-quality dashboard / Langfuse selector spans
  visualization** — Spec 15 may add lightweight observability;
  not core for Spec 13.
- **Force-fresh override per mission** — out of scope.
- **Cross-process LRU consistency** — single-process MVP; if
  Autumn ever scales horizontally, swap the in-process LRU for
  Redis or rely on Postgres alone.

## Files

### Create

- `apps/api/alembic/versions/0003_*_add_failure_count.py`
- `apps/api/app/persistence/selector_cache.py`
- `apps/api/app/tools/_purposes.py`
- `apps/api/app/tools/_storage.py`
- `apps/api/app/tools/_select.py`
- `apps/api/app/jobs/__init__.py`
- `apps/api/app/jobs/selector_sweep.py`
- `apps/api/tests/test_selector_repository.py`
- `apps/api/tests/test_select_main_content.py`
- `apps/web/widgets/task-lane-stack/selector-recovery-chip.tsx`
- `apps/web/widgets/task-lane-stack/selector-recovery-chip.test.tsx`

### Edit

- `apps/api/pyproject.toml` — add `cachetools`
- `apps/api/app/persistence/models.py` — add `failure_count`
  column
- `apps/api/app/persistence/repository.py` — extend
  `SelectorRepository` with five new methods, update `upsert`
- `apps/api/app/tools/http.py` — wire `select_main_content`
  before `MarkdownExtractor`
- `apps/api/app/tools/stealth.py` — same insertion
- `apps/api/app/tools/dynamic.py` — same insertion
- `apps/api/app/extract/__init__.py` — no signature change;
  documentation comment updates noting scoped-HTML inputs
- `apps/api/app/main.py` — register `selector_sweep_loop` on the
  lifespan TaskGroup
- `apps/web/features/run-mission/use-task-lanes.ts` — add
  `selectorRecoveryCount` and the projection case
- `apps/web/widgets/task-lane-stack/task-lane-row.tsx` — render
  the chip in the expanded body
- `apps/web/features/run-mission/use-task-lanes.test.ts` — add
  the new case
- `apps/web/shared/i18n/keys/en.ts` — append the 2 new keys

### Protected (do not touch)

- `apps/api/app/security.py`
- `apps/api/alembic/versions/0001_*.py`,
  `apps/api/alembic/versions/0002_*.py` (past migrations —
  add new migrations instead)
- `packages/sse-protocol/generated/**`
- `apps/web/components/ui/*`
- All previous protected files

## Verification

Run from the repo root.

- `cd apps/api && uv sync` resolves `cachetools`.
- `cd apps/api && uv run alembic upgrade head` succeeds; the
  new column appears in `\d saved_selectors`.
- `turbo run lint` exits 0.
- `turbo run typecheck` exits 0.
- `turbo run test` exits 0; the three new api tests and the new
  web hook test pass.
- `turbo run build` exits 0.

Manual:

- Run a URL-mode mission against `https://example.com/` twice.
  - First run: agent fetches; `select_main_content` saves a
    selector under `(example.com, main_content)`. The web shows
    no recovery chip.
  - In Neon: `SELECT * FROM saved_selectors WHERE domain = 'example.com'`
    returns one row with `hit_count=0`, `failure_count=0`.
  - Second run: agent re-fetches; the saved selector matches
    fresh (no adaptive fallback needed). Still no recovery chip.
- Force a DOM drift: simulate by editing the saved row's payload
  in Neon to refer to an element that no longer exists; run
  the mission a third time.
  - The `<main>` element matches fresh (because we always try
    fresh first). The adaptive path doesn't fire.
- Force a true adaptive match: pick a domain whose `<main>` tag
  is wrapped in a varying class. After the first run captures
  it, modify the page (in a fixture test server) so the saved
  selector misses; the adaptive fallback should re-locate via
  similarity. The recovery chip appears in the lane.
- Trigger three consecutive failures (point the saved selector
  at a non-existent fingerprint): on the third failure, the
  row is deleted from Neon; subsequent runs fall back to the
  Crawl4AI heuristic.
- Wait or simulate the 6-hour sweep tick; rows older than 30
  days disappear.
- Open Langfuse: `select_main_content` is implicit inside the
  tool span (no separate `@observe`); the trace shows a
  selector-recovery span when adaptive fires.

## Done when

- [ ] Every Verification line passes.
- [ ] No invariant in `context/architecture.md` violated.
  Specifically: invariant 8 — every `selector_recovered`
  emission and every `SelectorRepository` call key on the
  `(domain, purpose)` pair; no other key shape exists in code.
- [ ] `apps/api/app/security.py` was not edited.
- [ ] `apps/web/components/ui/*` was not edited.
- [ ] `prompt-engineer` agent rules pass: no agent prompts
  changed in this spec; existing `output_type`s and Langfuse
  traces unchanged.
- [ ] `i18n-keeper` agent flags zero hardcoded English strings
  in the new web files.
- [ ] `fsd-architect` agent flags zero layer violations.
- [ ] `context/progress-tracker.md` updated: Spec 13 to
  "Completed"; Spec 14 to "In Progress"; Open Question 5
  (cross-tenant selector visibility) stays unchanged — it's a
  deferred decision to revisit at scale.
- [ ] `scrape-pipeline-doctor` agent run on `apps/api/**`
  confirms invariant 8 (selector namespacing by
  `(domain, purpose)`) holds across every call site.
- [ ] `migration-doctor` agent run on
  `apps/api/alembic/versions/0003_*.py` confirms the
  `failure_count` column addition is migration-safe and the
  unique index on `(domain, purpose)` survives.
- [ ] `code-reviewer` agent run on the chunk produces
  `CODE_REVIEW.md` with `Verdict: Approve`.
- [ ] `simplify` skill review on the diff returns no actionable
  findings.

## Scrape reliability note

This spec ships the architecture's promise that "selectors saved
on run N are reused on run N+1 even when the site DOM has
shifted." Reliability impact:

1. **Lower latency on warm domains.** The first fetch on
   `example.com` saves a selector; every subsequent fetch on
   the same domain matches that selector before falling back to
   Crawl4AI's heuristic. The heuristic is only invoked on
   genuine drift.
2. **Self-healing on minor DOM changes.** When `example.com`
   renames a class or wraps `<main>` in a new container,
   Scrapling's similarity-based relocation finds it. Spec
   emits `selector_recovered` so the user sees the recovery in
   the lane chip — failures that would otherwise be silent
   become visible.
3. **Bounded staleness.** Three consecutive failures evict the
   selector; 30-day TTL prevents long-tail stale entries from
   bloating the DB; LRU caps memory.
4. **Observable.** The chip in the task lane and the
   `selector_recovered` SSE events make the recovery visible in
   the UI; Langfuse spans capture timing. Operators can
   distinguish "adaptive saved us" from "had to fall back to
   heuristic" without reading code.

What remains: user-facing cancellation + reaper + cost surface
(Spec 14), production hardening + e2e (Spec 15).
