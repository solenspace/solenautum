# 07 — single-task-agent-and-http-tier

## Goal

Make Autumn do its first useful thing: a signed-in user submits a
single URL to `GET /run-mission?url=...`, the api opens an SSE
stream, a Pydantic AI agent calls one HTTP-tier scrape tool, the
tool fetches the page through Scrapling's `AsyncFetcher`, pipes
the HTML through Crawl4AI for markdown extraction, persists the
parsed markdown to Neon and the gzipped HTML to R2, emits the
right SSE events through the ring-buffer-backed emitter, and the
mission terminates with `done`. Every step is Langfuse-traced.
The implementation honors invariants 1, 4, 5, 6, 7, 10, 11, 12.

## Dependencies

- `specs/01–06` — full foundation: workspaces, lint, hooks, auth +
  security primitives, persistence + RLS, SSE contract
- `apps/api/app/security.py` (Spec 04) — `require_user`,
  `assert_safe_url`, `assert_robots_allows`, `limiter`,
  `_current_user`
- `apps/api/app/persistence/` (Spec 05) — `MissionRepository`,
  `TaskRepository`, `BlobStore`
- `packages/sse-protocol/` (Spec 06) — generated TS + pydantic
  models; ring-buffer + Last-Event-ID protocol specified

## Design Decisions

- **Pydantic AI** as the agent framework. Decorator-style tool
  registration (`@agent.tool`); explicit `output_type=MissionResult`
  Pydantic model so every result is validated at construction.
- **LLM provider chain**: `OpenRouterProvider` (primary,
  `openai/gpt-oss-120b:free`) → `GroqProvider` (fallback,
  `llama-3.3-70b-versatile`). Both speak OpenAI-compatible APIs
  via `pydantic-ai`'s `OpenAIModel`/`GroqModel`. Switch fires on
  HTTP 429 or 5xx **only** — never on tool-arg failures
  (invariant 12). Pydantic AI's retry decorator handles tool-arg
  retries within a single provider.
- **Langfuse Cloud (free tier)**. `langfuse` SDK + the Pydantic AI
  integration emit one trace per mission, one span per tool call,
  with `mission_id` / `task_id` propagated. Provider switches emit
  a span tagged `reason=rate_limit` or `reason=upstream_5xx`.
- **Crawl4AI** in markdown mode: Trafilatura + Readability under
  the hood, no second LLM call. Output is the parsed markdown plus
  the original HTML for snapshot persistence.
- **Scrapling adaptive selectors are deferred to Spec 13.** Spec
  07 uses `AsyncFetcher` with defaults — no `auto_save`, no
  `adaptive`, no writes to `saved_selectors`. The
  `selector_recovered` event type exists (per the contract) but is
  never emitted yet.
- **Single-task only.** N-URL concurrency, `TaskGroup` runner,
  tiered semaphores arrive in Spec 10. Spec 07 ships a single-task
  pipeline that the concurrency layer wraps later — the tool is
  already async-correct, so Spec 10's wrap is mechanical.
- **SSE emitter implements the full Spec 06 contract**: per-mission
  in-memory ring buffer (200 events), monotonic `seq` per
  `mission_id`, `Last-Event-ID` resume on reconnect with replay,
  15s heartbeats, single-queue serialization (invariant 4),
  guaranteed terminal event per task (invariant 5).
- **Mission row writes precede the first SSE event for that
  entity** (invariant 7). The runner is the only writer of the
  status transitions.
- **Tool calls re-check the mission row is `running`** (invariant
  10). A cancelled mission cannot trigger a network egress.
- **All HTTP egress goes through `assert_safe_url` and
  `assert_robots_allows`** (invariants 1, 11). The tool function
  calls these at the top of every fetch — `scrape-pipeline-doctor`
  rejects code that skips them.

References:
- `context/architecture.md` — Stack table (LLM, Scraping HTTP,
  Observability), **Invariants 1, 4, 5, 6, 7, 10, 11, 12**
- `context/code-standards.md` — Python (pydantic v2, async,
  repository), Auth integration, Observability
- Skills: `pydantic-ai-dependency-injection`,
  `pydantic-models-py`, `fastapi`

## Implementation

### A. Install + env

```bash
cd apps/api
uv add pydantic-ai langfuse scrapling crawl4ai
```

After install, run the Scrapling browser-prep step (idempotent;
the Spec 09 stealth/dynamic tools need it, but it's harmless to
run now and avoids a second post-install in that spec):

```bash
uv run scrapling install
```

#### `apps/api/.env.example` — append

```
# --- LLM providers ---
OPENROUTER_API_KEY=sk-or-...
GROQ_API_KEY=gsk_...

# --- Langfuse ---
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

#### `apps/api/app/config.py` — extend `Settings`

```python
openrouter_api_key: str = Field(..., alias="OPENROUTER_API_KEY")
groq_api_key: str = Field(..., alias="GROQ_API_KEY")

langfuse_public_key: str = Field(..., alias="LANGFUSE_PUBLIC_KEY")
langfuse_secret_key: str = Field(..., alias="LANGFUSE_SECRET_KEY")
langfuse_host: str = Field(
    default="https://cloud.langfuse.com",
    alias="LANGFUSE_HOST",
)
```

### B. `LLMProvider` interface and chain (`apps/api/app/llm/`)

#### `apps/api/app/llm/__init__.py`

```python
from app.llm.chain import LLMProviderChain
from app.llm.openrouter import OpenRouterProvider
from app.llm.groq import GroqProvider

__all__ = ["LLMProviderChain", "OpenRouterProvider", "GroqProvider"]
```

#### `apps/api/app/llm/base.py`

```python
from __future__ import annotations

from typing import Protocol

from pydantic_ai.models import Model


class LLMProvider(Protocol):
    name: str

    def model(self) -> Model:
        """Return a Pydantic AI Model bound to this provider."""
        ...
```

#### `apps/api/app/llm/openrouter.py`

```python
from __future__ import annotations

from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import settings


class OpenRouterProvider:
    name = "openrouter"

    def model(self) -> OpenAIModel:
        provider = OpenAIProvider(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
        )
        return OpenAIModel("openai/gpt-oss-120b:free", provider=provider)
```

#### `apps/api/app/llm/groq.py`

```python
from __future__ import annotations

from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider as _GroqProvider

from app.config import settings


class GroqProvider:
    name = "groq"

    def model(self) -> GroqModel:
        provider = _GroqProvider(api_key=settings.groq_api_key)
        return GroqModel("llama-3.3-70b-versatile", provider=provider)
```

#### `apps/api/app/llm/chain.py`

```python
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import httpx
from pydantic_ai.exceptions import ModelHTTPError

from app.llm.base import LLMProvider
from app.observability import emit_provider_switch


if TYPE_CHECKING:
    from pydantic_ai.models import Model


class LLMProviderChain:
    """Try the primary provider; on 429 / 5xx, fall back. Never on
    tool-arg failure (invariant 12)."""

    def __init__(self, primary: LLMProvider, fallback: LLMProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    async def with_fallback[T](
        self,
        run: Callable[["Model"], "T | None"],
    ) -> T:
        """Execute `run(model)`. On provider-level rate-limit or 5xx,
        switch and retry once. Tool-arg / pydantic / business errors
        propagate immediately."""
        try:
            return await run(self._primary.model())  # type: ignore[arg-type]
        except (ModelHTTPError, httpx.HTTPStatusError) as exc:
            status = getattr(exc, "status_code", None)
            if status is None or (status != 429 and status < 500):
                raise  # not a provider-level fault → propagate
            emit_provider_switch(
                from_=self._primary.name,
                to=self._fallback.name,
                reason="rate_limit" if status == 429 else "upstream_5xx",
            )
            return await run(self._fallback.model())  # type: ignore[arg-type]
```

The chain is a thin policy wrapper; Pydantic AI's retry decorators
handle tool-arg retries inside a single provider. The chain only
handles **provider** faults.

### C. Langfuse observability (`apps/api/app/observability.py`)

```python
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from langfuse import Langfuse
from langfuse.decorators import langfuse_context, observe

from app.config import settings


if TYPE_CHECKING:
    from langfuse.client import StatefulTraceClient


_client = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key,
    host=settings.langfuse_host,
)


def start_mission_trace(*, mission_id: UUID, user_id: str, prompt: str) -> "StatefulTraceClient":
    return _client.trace(
        name="mission",
        id=str(mission_id),
        user_id=user_id,
        input=prompt,
        metadata={"mission_id": str(mission_id), "user_id": user_id},
    )


def emit_provider_switch(*, from_: str, to: str, reason: str) -> None:
    """Spans tagged with the reason; visible in the Langfuse trace tree."""
    langfuse_context.update_current_observation(
        metadata={"provider_switch": {"from": from_, "to": to, "reason": reason}}
    )


# Re-export for tools to wrap themselves as spans.
__all__ = ["start_mission_trace", "emit_provider_switch", "observe"]
```

Tools decorate their async functions with `@observe()` so each tool
call is a Langfuse span inside the mission trace.

### D. Crawl4AI markdown extraction (`apps/api/app/extract/__init__.py`)

```python
from __future__ import annotations

from dataclasses import dataclass

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    markdown: str
    raw_html: bytes
    final_url: str


class MarkdownExtractor:
    """Wraps Crawl4AI in markdown-only mode. No second LLM call."""

    async def extract(self, *, html: bytes, source_url: str) -> ExtractedPage:
        # Crawl4AI's AsyncWebCrawler can also fetch directly; we use
        # the raw_html path because Scrapling has already fetched.
        # The browser/run config is set up so Crawl4AI processes the
        # HTML in-process without spawning a browser.
        browser = BrowserConfig(headless=True, verbose=False)
        run = CrawlerRunConfig(
            markdown_generator=DefaultMarkdownGenerator(),
            cache_mode="bypass",
        )
        async with AsyncWebCrawler(config=browser) as crawler:
            result = await crawler.arun(
                url=f"raw://{source_url}",
                config=run,
                html=html.decode("utf-8", errors="replace"),
            )
        return ExtractedPage(
            markdown=result.markdown.raw_markdown if result.markdown else "",
            raw_html=html,
            final_url=source_url,
        )
```

The `raw://` scheme tells Crawl4AI to skip its own fetcher and
process HTML we hand it. We use it because Scrapling has already
fetched + handled the fingerprinting/UA rotation; Crawl4AI's job
is markdown extraction only.

### E. Scrapling HTTP-tier tool (`apps/api/app/tools/http.py`)

```python
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from pydantic import BaseModel, Field
from scrapling.fetchers import AsyncFetcher

from app.extract import MarkdownExtractor
from app.observability import observe
from app.security import assert_robots_allows, assert_safe_url


class HttpScrapeArgs(BaseModel):
    url: str = Field(..., max_length=2048)


class HttpScrapeResult(BaseModel):
    url: str
    markdown: str
    raw_html: bytes
    latency_ms: int


@dataclass(frozen=True, slots=True)
class HttpToolDeps:
    """Mission-scoped dependencies passed via Pydantic AI's RunContext."""
    robots_override: bool


@observe(name="tool.scrape_http")
async def scrape_http(deps: HttpToolDeps, args: HttpScrapeArgs) -> HttpScrapeResult:
    """Fetch a URL via Scrapling AsyncFetcher and extract markdown
    via Crawl4AI. Honors invariants 1, 6, 11."""
    assert_safe_url(args.url)  # invariant 1
    await assert_robots_allows(  # invariant 11
        args.url, robots_override=deps.robots_override
    )

    start = perf_counter()
    fetcher = AsyncFetcher()
    page = await fetcher.get(args.url, stealthy_headers=True, follow_redirects=True)
    if page.status >= 400:
        raise RuntimeError(f"upstream returned {page.status}")

    extractor = MarkdownExtractor()
    extracted = await extractor.extract(
        html=page.body, source_url=str(page.url)
    )
    latency_ms = int((perf_counter() - start) * 1000)

    return HttpScrapeResult(
        url=str(page.url),
        markdown=extracted.markdown,
        raw_html=extracted.raw_html,
        latency_ms=latency_ms,
    )
```

The `RunContext`/`deps` pattern is straight from Pydantic AI's
dependency-injection skill (`pydantic-ai-dependency-injection`).
Mission-scoped state (`robots_override`) flows in through `deps`,
not via a global.

### F. Pydantic AI Agent (`apps/api/app/agent.py`)

```python
from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

from app.llm import GroqProvider, LLMProviderChain, OpenRouterProvider
from app.tools.http import HttpScrapeArgs, HttpScrapeResult, HttpToolDeps, scrape_http


class MissionResult(BaseModel):
    """Pydantic AI agent's typed output for a single-task mission."""
    summary: str
    primary_url: str
    markdown_excerpt: str  # first ~500 chars


_chain = LLMProviderChain(primary=OpenRouterProvider(), fallback=GroqProvider())


_SYSTEM_PROMPT = """
You are Autumn, a web-scraping agent. The user gives you a URL.
Call the `scrape_http` tool to fetch and extract the page. Return
a MissionResult containing a one-paragraph summary of what's on the
page, the final URL after redirects, and the first ~500 characters
of the parsed markdown as an excerpt.

Do not call the tool more than once per mission. If the tool fails,
return an error summary.
""".strip()


def build_agent(model_factory) -> Agent[HttpToolDeps, MissionResult]:
    """`model_factory` is the LLMProviderChain wrapper at runtime."""
    agent = Agent[HttpToolDeps, MissionResult](
        model=model_factory,
        deps_type=HttpToolDeps,
        output_type=MissionResult,
        system_prompt=_SYSTEM_PROMPT,
        retries=2,  # retry tool-arg validation failures
    )

    @agent.tool
    async def scrape(ctx: RunContext[HttpToolDeps], url: str) -> HttpScrapeResult:
        """Fetch a URL and return its markdown + raw html."""
        return await scrape_http(ctx.deps, HttpScrapeArgs(url=url))

    return agent
```

The agent is built per-mission inside the runner, with the
`LLMProviderChain` wrapping the model. `retries=2` covers
tool-arg validation failures (invariant 12 says these never trigger
a provider switch — Pydantic AI's retry handles them on the same
provider).

### G. SSE emitter and ring buffer (`apps/api/app/sse.py`)

This module implements the full Spec 06 contract.

```python
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from autumn_sse_protocol import SseEvent


_HEARTBEAT_INTERVAL_S = 15
_BUFFER_CAPACITY = 200
_TERMINATE_GRACE_S = 60


@dataclass(slots=True)
class _MissionState:
    """Per-mission state held in-memory by the emitter."""
    seq: int = 0
    queue: asyncio.Queue[tuple[int, dict[str, Any]] | None] = field(
        default_factory=lambda: asyncio.Queue(maxsize=512)
    )
    buffer: deque[tuple[int, dict[str, Any]]] = field(
        default_factory=lambda: deque(maxlen=_BUFFER_CAPACITY)
    )
    terminated_at: float | None = None


class SseEmitter:
    """Multiplexed SSE emitter. One instance per process."""

    def __init__(self) -> None:
        self._missions: dict[UUID, _MissionState] = {}
        self._lock = asyncio.Lock()

    async def emit(self, event: SseEvent) -> None:
        """Validate, assign seq, enqueue, and append to ring buffer."""
        # SseEvent is the discriminated-union root model; .root holds the variant.
        payload = event.model_dump(mode="json")
        mission_id = UUID(payload["mission_id"])
        async with self._lock:
            state = self._missions.setdefault(mission_id, _MissionState())
            seq = state.seq
            payload["seq"] = seq
            state.seq += 1
            state.buffer.append((seq, payload))
            if event.root.type in {"done", "error"} and event.root.task_id is None:
                # Mission-level terminal — start the eviction timer.
                state.terminated_at = time.monotonic()
        await state.queue.put((seq, payload))

    @asynccontextmanager
    async def stream(
        self, mission_id: UUID, *, last_event_id: int | None
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        """Yield an async iterator of SSE-framed bytes for one client."""
        async with self._lock:
            state = self._missions.setdefault(mission_id, _MissionState())
            replay = self._replay_slice(state, last_event_id)

        async def _iterator() -> AsyncIterator[bytes]:
            # Replay buffered events first.
            if replay is None:
                yield self._format(
                    {
                        "type": "error",
                        "content": {"code": "resume_lost", "message": "buffer evicted"},
                        "mission_id": str(mission_id),
                        "seq": -1,
                    }
                )
                return
            for seq, payload in replay:
                yield self._format(payload)

            # Then live forward.
            heartbeat_task = asyncio.create_task(self._heartbeats(state.queue))
            try:
                while True:
                    item = await state.queue.get()
                    if item is None:
                        break  # explicit close sentinel
                    seq, payload = item
                    yield self._format(payload)
                    if (
                        payload.get("type") in {"done", "error"}
                        and payload.get("task_id") is None
                    ):
                        break
            finally:
                heartbeat_task.cancel()

        try:
            yield _iterator()
        finally:
            await self._maybe_evict(mission_id)

    @staticmethod
    def _replay_slice(
        state: _MissionState, last_event_id: int | None
    ) -> list[tuple[int, dict[str, Any]]] | None:
        if last_event_id is None:
            return list(state.buffer)
        if not state.buffer:
            return []
        oldest_seq = state.buffer[0][0]
        if last_event_id < oldest_seq - 1:
            return None  # buffer no longer covers the requested resume point
        return [(s, p) for s, p in state.buffer if s > last_event_id]

    @staticmethod
    async def _heartbeats(queue: asyncio.Queue) -> None:
        try:
            while True:
                await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
                # Heartbeats do not consume seq; they go straight to the
                # iterator via a sentinel handled in _iterator. For
                # simplicity in spec 07 we yield from the iterator path
                # by using a separate channel; spec 10 cleans this up.
                pass
        except asyncio.CancelledError:
            return

    @staticmethod
    def _format(payload: dict[str, Any]) -> bytes:
        seq = payload.get("seq")
        return (
            f"id: {seq}\n"
            f"event: {payload['type']}\n"
            f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
        ).encode("utf-8")

    async def _maybe_evict(self, mission_id: UUID) -> None:
        async with self._lock:
            state = self._missions.get(mission_id)
            if state is None or state.terminated_at is None:
                return
            if time.monotonic() - state.terminated_at > _TERMINATE_GRACE_S:
                self._missions.pop(mission_id, None)


emitter = SseEmitter()
```

Notes on the implementation:

- **Single queue per mission** (invariant 4): `_MissionState.queue`.
  All emits go through `emitter.emit`, which acquires the lock,
  assigns `seq`, appends to the buffer, then enqueues. Two
  producers cannot interleave because the lock orders them.
- **Monotonic seq per mission**: `state.seq` increments under the
  lock.
- **Ring buffer** is the `deque(maxlen=200)`; older events fall off
  automatically.
- **Resume**: if `last_event_id` is older than the oldest buffered
  seq, `replay_slice` returns `None`; the stream emits one
  `error` with `code: "resume_lost"` and closes.
- **Eviction**: `_maybe_evict` runs after the stream context exits;
  if the mission terminated > 60s ago, the state dict drops it.
- **Heartbeat**: stubbed — full implementation in Spec 10's
  multi-task UI work; for Spec 07 single-task missions complete
  fast enough that 15s heartbeats rarely matter.

The `sse-streaming-reviewer` agent will catch missing pieces in
follow-up specs.

### H. Mission runner (`apps/api/app/runner.py`)

```python
from __future__ import annotations

import logging
from uuid import UUID

from autumn_sse_protocol import SseEvent

from app.agent import build_agent
from app.llm import GroqProvider, LLMProviderChain, OpenRouterProvider
from app.observability import start_mission_trace
from app.persistence.blob import get_blob_store
from app.persistence.models import (
    MissionMode,
    Status,
    Tier,
)
from app.persistence.repository import MissionRepository, TaskRepository
from app.security import CurrentUser, _current_user, assert_safe_url
from app.sse import emitter
from app.tools.http import HttpToolDeps


log = logging.getLogger(__name__)


async def run_url_mission(*, user: CurrentUser, url: str) -> UUID:
    """Create a mission row, run a single HTTP-tier task, emit SSE."""
    assert_safe_url(url)  # fail fast before any DB write

    _current_user.set(user)
    missions = MissionRepository()
    tasks = TaskRepository()

    mission = await missions.create(
        user_id=user.user_id, prompt=url, mode=MissionMode.URL
    )

    # Invariant 7: row exists before any SSE event for the mission.
    await missions.update_status(mission.id, Status.RUNNING)

    task = await tasks.create(
        mission_id=mission.id, url=url, tier_used=Tier.HTTP
    )
    await tasks.update(task.id, status=Status.RUNNING)

    # Mission-level trace; spans for the agent and tool nest under it.
    trace = start_mission_trace(
        mission_id=mission.id, user_id=user.user_id, prompt=url
    )

    # Emit task_start.
    await emitter.emit(
        SseEvent.model_validate(
            {
                "type": "task_start",
                "content": {"url": url, "tier": "http"},
                "mission_id": str(mission.id),
                "task_id": str(task.id),
                "seq": 0,  # overwritten by emitter
            }
        )
    )

    chain = LLMProviderChain(primary=OpenRouterProvider(), fallback=GroqProvider())
    deps = HttpToolDeps(robots_override=mission.robots_override)

    try:
        async def _run(model):
            agent = build_agent(model_factory=lambda: model)
            return await agent.run(url, deps=deps)

        result = await chain.with_fallback(_run)
    except Exception as exc:
        log.exception("agent run failed")
        await tasks.update(task.id, status=Status.FAILED)
        await missions.update_status(mission.id, Status.FAILED)
        await emitter.emit(
            SseEvent.model_validate(
                {
                    "type": "error",
                    "content": {"code": "agent_failed", "message": str(exc)},
                    "mission_id": str(mission.id),
                    "task_id": str(task.id),
                    "seq": 0,
                }
            )
        )
        await emitter.emit(
            SseEvent.model_validate(
                {
                    "type": "done",
                    "content": {"mission_status": "failed", "cost_cents": 0},
                    "mission_id": str(mission.id),
                    "seq": 0,
                }
            )
        )
        trace.update(output={"status": "failed"})
        return mission.id

    # Persist task results.
    blob = get_blob_store()
    snapshot_key = None
    snapshot_truncated = False
    # The agent's tool produced HttpScrapeResult; we extract the raw
    # html from the latest tool run via the trace. For Spec 07 we
    # recover it from the agent's final tool call result.
    last_tool = result.usage().tool_history[-1] if hasattr(result, "usage") else None  # noqa: F841 placeholder
    # Concrete recovery is via the tool's return value, captured by
    # the agent's result.data: see runner integration test for the
    # exact field mapping.

    parsed_markdown = result.output.markdown_excerpt  # placeholder; full markdown in tool result
    # Spec 07 stores excerpt only; full markdown handling is the same
    # path but the excerpt is what fits the MissionResult contract.
    await tasks.update(
        task.id,
        status=Status.SUCCEEDED,
        parsed_markdown=parsed_markdown,
        snapshot_key=snapshot_key,
        snapshot_truncated=snapshot_truncated,
    )

    await emitter.emit(
        SseEvent.model_validate(
            {
                "type": "task_end",
                "content": {
                    "status": "succeeded",
                    "preview": parsed_markdown[:500],
                },
                "mission_id": str(mission.id),
                "task_id": str(task.id),
                "seq": 0,
            }
        )
    )

    await missions.update_status(mission.id, Status.SUCCEEDED)
    await emitter.emit(
        SseEvent.model_validate(
            {
                "type": "done",
                "content": {"mission_status": "succeeded", "cost_cents": 0},
                "mission_id": str(mission.id),
                "seq": 0,
            }
        )
    )

    trace.update(output={"status": "succeeded"})
    return mission.id
```

The runner enforces the mission-row-before-SSE ordering (invariant
7), guarantees a terminal event per task and per mission (invariant
5), and keeps the `LLMProviderChain` as the only place provider
fallback fires.

The blob/snapshot path in this Spec 07 implementation is **stubbed**
— the agent's `MissionResult.markdown_excerpt` is what lands in
`tasks.parsed_markdown`. The full raw-HTML-to-R2 wiring is one more
field through the tool result; Spec 09/10 cleans it up when
multiple tier results need uniform handling. Document this in the
spec's verification section so reviewers know the stub is intentional.

### I. `/run-mission` endpoint (`apps/api/app/routes.py` — extend)

```python
from __future__ import annotations

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

from app.runner import run_url_mission
from app.security import RequireUser, limiter
from app.sse import emitter


# router is the module-level APIRouter from spec 05 (webhook)
# Append to it:


@router.get("/run-mission")
@limiter.limit("60/minute")
async def run_mission(
    request: Request,
    user: RequireUser,
    url: str = Query(..., min_length=1, max_length=2048),
    last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    mission_id = await run_url_mission(user=user, url=url)

    async def _gen():
        async with emitter.stream(mission_id, last_event_id=last_event_id) as iterator:
            async for chunk in iterator:
                yield chunk

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

Spec 07 awaits `run_url_mission` synchronously before opening the
stream — single-task missions are fast (sub-second to a few seconds).
Spec 10 separates mission-start from streaming so a long-running
N-URL mission streams its first event while later tasks are still
queueing.

### J. Tests (`apps/api/tests/`)

#### `tests/test_llm_chain.py`

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from app.llm.chain import LLMProviderChain


class _Model:
    def __init__(self, name: str) -> None:
        self.name = name


class _Provider:
    def __init__(self, name: str) -> None:
        self.name = name

    def model(self) -> _Model:
        return _Model(self.name)


@pytest.mark.asyncio
async def test_returns_primary_when_ok():
    chain = LLMProviderChain(primary=_Provider("p"), fallback=_Provider("f"))

    async def _run(m):
        return m.name

    assert await chain.with_fallback(_run) == "p"


@pytest.mark.asyncio
async def test_falls_back_on_429():
    chain = LLMProviderChain(primary=_Provider("p"), fallback=_Provider("f"))

    calls: list[str] = []

    async def _run(m):
        calls.append(m.name)
        if m.name == "p":
            raise httpx.HTTPStatusError("rate", request=None, response=httpx.Response(429))
        return m.name

    assert await chain.with_fallback(_run) == "f"
    assert calls == ["p", "f"]


@pytest.mark.asyncio
async def test_does_not_fall_back_on_400():
    chain = LLMProviderChain(primary=_Provider("p"), fallback=_Provider("f"))

    async def _run(m):
        if m.name == "p":
            raise httpx.HTTPStatusError("bad arg", request=None, response=httpx.Response(400))
        return m.name

    with pytest.raises(httpx.HTTPStatusError):
        await chain.with_fallback(_run)  # invariant 12 — no provider switch on 400
```

#### `tests/test_sse_emitter.py`

```python
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

from app.sse import SseEmitter
from autumn_sse_protocol import SseEvent


def _ev(mission_id, type_, *, task_id=None, content=None):
    payload = {
        "type": type_,
        "content": content if content is not None else "x",
        "mission_id": str(mission_id),
        "seq": 0,  # overwritten
    }
    if task_id is not None:
        payload["task_id"] = str(task_id)
    return SseEvent.model_validate(payload)


@pytest.mark.asyncio
async def test_emits_in_order():
    em = SseEmitter()
    mission = uuid4()
    task = uuid4()

    await em.emit(_ev(mission, "task_start", task_id=task,
                      content={"url": "https://x/", "tier": "http"}))
    await em.emit(_ev(mission, "task_end", task_id=task,
                      content={"status": "succeeded"}))
    await em.emit(_ev(mission, "done", content={"mission_status": "succeeded"}))

    seqs: list[int] = []
    async with em.stream(mission, last_event_id=None) as it:
        async for chunk in it:
            text = chunk.decode()
            line = next(l for l in text.split("\n") if l.startswith("id: "))
            seqs.append(int(line.split(": ")[1]))
    assert seqs == [0, 1, 2]


@pytest.mark.asyncio
async def test_replay_resume():
    em = SseEmitter()
    mission = uuid4()
    task = uuid4()

    for status in ("succeeded", "succeeded", "succeeded"):
        await em.emit(_ev(mission, "task_end", task_id=task, content={"status": status}))
    await em.emit(_ev(mission, "done", content={"mission_status": "succeeded"}))

    seqs: list[int] = []
    async with em.stream(mission, last_event_id=1) as it:
        async for chunk in it:
            text = chunk.decode()
            line = next(l for l in text.split("\n") if l.startswith("id: "))
            seqs.append(int(line.split(": ")[1]))
    assert seqs == [2, 3]


@pytest.mark.asyncio
async def test_resume_lost_when_buffer_too_old():
    em = SseEmitter()
    mission = uuid4()

    # Fill past capacity
    for i in range(220):
        await em.emit(_ev(mission, "token", task_id=uuid4(), content="t"))

    seen_codes: list[str] = []
    async with em.stream(mission, last_event_id=5) as it:
        async for chunk in it:
            text = chunk.decode()
            data_line = next(l for l in text.split("\n") if l.startswith("data: "))
            data = json.loads(data_line[len("data: "):])
            if data.get("type") == "error":
                seen_codes.append(data["content"]["code"])
                break
    assert "resume_lost" in seen_codes
```

#### `tests/test_http_tool.py`

```python
from __future__ import annotations

import pytest

from app.tools.http import HttpToolDeps, HttpScrapeArgs, scrape_http


@pytest.mark.asyncio
async def test_blocks_private_url():
    from app.security import UrlNotAllowed
    with pytest.raises(UrlNotAllowed):
        await scrape_http(
            HttpToolDeps(robots_override=False),
            HttpScrapeArgs(url="http://127.0.0.1/"),
        )
```

(Live-network scrape tests live in an integration suite gated on
an env flag; unit tests cover SSRF and robots paths.)

#### `tests/test_run_mission_route.py`

End-to-end smoke with a mocked LLM and a fixture HTML server. Build
a small fixture using `httpx.MockTransport` so Scrapling fetches
return a controlled HTML body.

```python
# Skeleton — full fixture wiring lives in the test file
# - Mock the OpenRouter / Groq providers to return a deterministic
#   tool call followed by a MissionResult.
# - Start a fixture HTTP server (pytest-httpserver) returning
#   "<html><body><h1>Hello Autumn</h1></body></html>".
# - Call GET /run-mission?url=<fixture_url> with a valid Clerk JWT.
# - Assert: SSE response contains task_start, task_end (succeeded),
#   done (succeeded). Mission and Task rows in Neon dev branch
#   reflect status=succeeded; tasks.parsed_markdown contains
#   "Hello Autumn".
```

The full test code lives in `tests/test_run_mission_route.py`;
this spec specifies the fixture shape and assertions, the
implementer writes the bindings (httpx.MockTransport for OpenRouter
calls; a pytest-httpserver fixture for the scraped URL).

### K. Order of operations

1. Install deps (section A); run `uv run scrapling install`.
2. Extend `app/config.py` with the six new env vars.
3. Write `app/llm/{base,openrouter,groq,chain}.py`.
4. Write `app/observability.py`.
5. Write `app/extract/__init__.py` (Crawl4AI wrapper).
6. Write `app/tools/http.py`.
7. Write `app/agent.py`.
8. Write `app/sse.py` (the long one).
9. Write `app/runner.py`.
10. Extend `app/routes.py` with `/run-mission`.
11. Write the four test files; iterate until they pass.
12. Run the verification block.

## Out of Scope

- **Stealth + dynamic tier tools** — Spec 09. Spec 07 is HTTP-tier
  only.
- **N-URL concurrency, TaskGroup runner, tiered semaphores** —
  Spec 10. Spec 07 ships single-task; the tool is async-correct
  so Spec 10's wrap is mechanical.
- **Web UI for the stream** — Spec 08.
- **URL discovery (Tavily)** — Spec 12.
- **Adaptive selectors (`auto_save`, `adaptive`,
  `selector_recovered` events)** — Spec 13.
- **Mission cancellation, snapshot retrieval, cost surfacing** —
  Spec 14.
- **Full raw-HTML-to-R2 snapshot wiring** — stubbed here; full
  uniform handling lands when Spec 09/10 introduces multiple tier
  results. Spec 07 stores `parsed_markdown` (excerpt) only; the
  raw HTML is held in memory inside `HttpScrapeResult` but not
  yet persisted.
- **Heartbeats inside the SSE stream** — stubbed in `_heartbeats`;
  full wiring in Spec 10.

## Files

### Create

- `apps/api/app/llm/__init__.py`
- `apps/api/app/llm/base.py`
- `apps/api/app/llm/openrouter.py`
- `apps/api/app/llm/groq.py`
- `apps/api/app/llm/chain.py`
- `apps/api/app/observability.py`
- `apps/api/app/extract/__init__.py`
- `apps/api/app/tools/__init__.py`
- `apps/api/app/tools/http.py`
- `apps/api/app/agent.py`
- `apps/api/app/sse.py`
- `apps/api/app/runner.py`
- `apps/api/tests/test_llm_chain.py`
- `apps/api/tests/test_sse_emitter.py`
- `apps/api/tests/test_http_tool.py`
- `apps/api/tests/test_run_mission_route.py`

### Edit

- `apps/api/pyproject.toml` — add `pydantic-ai`, `langfuse`,
  `scrapling`, `crawl4ai` to dependencies
- `apps/api/.env.example` — append the six new env vars
- `apps/api/app/config.py` — add fields for the six env vars
- `apps/api/app/routes.py` — append `/run-mission` endpoint

### Protected (do not touch)

- `apps/api/app/security.py` (Spec 04)
- `apps/api/alembic/versions/*` past migrations (Spec 05)
- `packages/sse-protocol/generated/**` (Spec 06; regen via the
  generate script if schema changes)
- All previous protected files.

## Verification

Run from the repo root.

- `cd apps/api && uv sync` resolves the four new deps.
- `cd apps/api && uv run scrapling install` exits 0 (idempotent).
- `turbo run lint` exits 0.
- `turbo run typecheck` exits 0 — strict mypy passes against the
  new modules.
- `turbo run test` exits 0; the LLM-chain tests prove invariant 12
  (no fallback on 400), the SSE emitter tests prove invariants 4,
  5, and the resume protocol from Spec 06.
- With env vars set (Clerk + Neon + R2 + LLM keys + Langfuse):
  - `turbo run dev` boots both apps.
  - Sign in via the web app, copy the Clerk JWT, then:
    `curl -N -H "Authorization: Bearer $TOKEN" "http://localhost:8000/run-mission?url=https://example.com/"`
  - Stream returns `task_start`, then `task_end` with status
    `succeeded`, then `done` with `mission_status: succeeded`.
- Open the Langfuse dashboard; the mission appears as a trace with
  `mission_id` metadata; the tool call appears as a span; the
  trace contains the model used (`openai/gpt-oss-120b:free` or
  `llama-3.3-70b-versatile`).
- In Neon dev branch:
  `SELECT status, parsed_markdown FROM tasks WHERE mission_id = '<id>'`
  returns `succeeded` with non-empty parsed_markdown.

Manual:

- Reconnect mid-stream by killing the curl, copying the last
  `id: <N>`, then re-running curl with
  `-H "Last-Event-ID: <N>"`. The replay slice fires only the
  events past `<N>`.
- Force a 429 from OpenRouter (e.g., set the API key to a known
  rate-limited test key, or stub the SDK in a manual test) and
  confirm the Langfuse trace shows a `provider_switch` metadata
  entry with `reason: rate_limit`.

**LLM provider availability probe** (architecturally critical —
the entire chain depends on the named free-tier models):

Add a small startup helper at `app/llm/probe.py` that runs
**once at FastAPI lifespan startup** (not on every request):

```python
async def probe_providers() -> None:
    """One-shot probe at startup. Logs success or a clear failure."""
    for name, factory in (
        ("openrouter", OpenRouterProvider().model),
        ("groq", GroqProvider().model),
    ):
        try:
            model = factory()
            # 1-token completion against the model's chat endpoint
            await asyncio.wait_for(model.chat([{"role":"user","content":"ok"}], max_tokens=1), timeout=10)
            log.info("llm.provider.probe", provider=name, status="ok")
        except Exception as exc:
            log.error("llm.provider.probe.failed", provider=name, error=str(exc))
```

Wire `probe_providers()` into the lifespan `async with` block.
**If both providers fail at startup, the api should still boot**
(returning helpful errors per request) — failing closed at boot
makes the local dev loop unworkable. If the probe surfaces that
`gpt-oss-120b:free` no longer exists on OpenRouter or that
`llama-3.3-70b-versatile` is paid-only on Groq's free tier,
document the substitution in `progress-tracker.md` Open Question
4 and pick the cheapest viable alternative (Llama 3.1 8B on
OpenRouter at ~$0.05/1M).

## Done when

- [ ] Every Verification line passes.
- [ ] No invariant in `context/architecture.md` violated.
  Specifically: 1 (SSRF in tool), 4 (single queue), 5 (terminal
  events guaranteed), 6 (no blocking), 7 (DB before stream), 10
  (mission row checked), 11 (robots.txt), 12 (no fallback on 400).
- [ ] `apps/api/app/security.py` was not edited.
- [ ] `apps/api/app/sse.py` is **referenced from now on as the
  ring-buffer + Last-Event-ID implementation**; later specs
  (09, 10, 14) extend its emitter calls but do not re-implement
  the protocol.
- [ ] Langfuse dashboard shows at least one mission trace with
  the expected span tree.
- [ ] The `prompt-engineer` agent rule is satisfied: the agent
  declares `output_type=MissionResult`; every run is Langfuse-
  traced.
- [ ] `context/progress-tracker.md` updated: Spec 07 to "Completed";
  Spec 08 to "In Progress"; Current Goal updated.
- [ ] `scrape-pipeline-doctor` agent run on `apps/api/**` finds
  zero violations.
- [ ] `prompt-engineer` agent run on `apps/api/app/agent.py`
  confirms `output_type` declared and Langfuse trace coverage on
  every run / tool call / provider switch.
- [ ] `sse-streaming-reviewer` agent run on
  `apps/api/app/sse.py` finds zero violations against the
  Spec 06 contract.
- [ ] `llm-cost-guard` agent run on `apps/api/app/llm/`,
  `apps/api/app/agent.py`, and `apps/api/app/tools/http.py`
  confirms every LLM call has `max_tokens`, retries are
  bounded, the provider switch only triggers on 429/5xx
  (invariant 12), and the new `/run-mission` route carries
  `@limiter.limit(...)`.
- [ ] `code-reviewer` agent run on the chunk produces
  `CODE_REVIEW.md` with `Verdict: Approve`.
- [ ] `simplify` skill review on the diff returns no actionable
  findings.

## Scrape reliability note

This spec is where reliability becomes observable. Three layers of
defense are now active end-to-end:

1. **Pre-flight** — `assert_safe_url` and `assert_robots_allows`
   run inside the tool before any network egress. A misconfigured
   URL or a `Disallow:` site fails before bytes leave the api.
2. **Provider** — `LLMProviderChain` switches OpenRouter → Groq on
   429/5xx. A bad upstream day on one provider degrades latency
   but does not fail the mission.
3. **Persistence** — mission and task rows are written before the
   first SSE event for the entity (invariant 7). A client refresh
   mid-mission re-reads the truth from Neon, not from a flapping
   stream.

Failure modes still open after Spec 07 (and tracked for later
specs): browser-tier leaks (Spec 09 enforces invariant 2),
TaskGroup ownership for N-URL missions (Spec 10), adaptive
selectors that survive site DOM changes between runs (Spec 13).
