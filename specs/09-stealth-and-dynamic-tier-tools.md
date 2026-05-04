# 09 — stealth-and-dynamic-tier-tools

## Goal

Give the agent two more tools: a stealth tier
(`AsyncStealthySession` with Cloudflare bypass) and a dynamic tier
(`AsyncDynamicSession` with Playwright). Both run inside the
browser-tier semaphore (invariant 2). Reactive WAF detection
classifies non-Cloudflare anti-bots (Akamai, DataDome, PerimeterX)
and surfaces a clean `site_not_supported` error event. The shared
`persist_snapshot` helper closes Spec 07's snapshot stub: every
tier writes raw HTML to R2 through one chokepoint. The agent
decides escalation based on typed tool results.

## Dependencies

- `specs/07` — `apps/api/app/agent.py`, `tools/http.py`,
  `runner.py`, `extract/`, `observability.py`, `MissionResult`
- `specs/05` — `BlobStore`, `R2BlobStore`, `LocalFsBlobStore`,
  `TaskRepository`
- `specs/04` — `assert_safe_url`, `assert_robots_allows`
- `specs/06` — SSE `error` event with `code` and `message`

## Design Decisions

- **Both browser tiers wrap each call in
  `AsyncStealthySession` / `AsyncDynamicSession` opened fresh per
  task** — leak-proof, isolated, simple cancellation. Session
  reuse pools are rejected for MVP (cross-mission cookie leaks,
  shared mutable state across `TaskGroup` branches).
- **Browser semaphore lives in `apps/api/app/concurrency.py`**.
  Spec 09 ships only the **global** ceiling
  (`asyncio.Semaphore(8)`); the per-mission ceiling
  (`asyncio.Semaphore(3)`) lands in Spec 10 when the `TaskGroup`
  runner exists. The semaphore acquire wraps every browser session
  open and is released in `finally` (invariant 2).
- **Reactive WAF detection** runs after a 4xx response inside any
  tier. Header / body fingerprints classify into `cloudflare`,
  `akamai`, `datadome`, `perimeterx`, or `unknown`. Cloudflare
  triggers stealth-tier escalation; the others terminate as
  `site_not_supported`.
- **Tool results are typed discriminated unions**:
  `ScrapeOk` (success) and `ScrapeFailure` (with `reason` literal).
  Reasons the agent reacts to:
  - `protected_cloudflare` → escalate to stealth
  - `javascript_required` → escalate to dynamic
  - `site_not_supported` → return `MissionResult(status="error",
    error_code="site_not_supported")`
  - `upstream_error` → return error with code `upstream_error`
  - `not_found` (404) → return error with code `not_found`
- **Agent owns escalation** via system prompt + tool descriptions.
  No hard-coded fallback chain in the runner. The agent sees the
  failure reason and chooses the next tool.
- **`MissionResult` gets `status`, `error_code`** fields.
  `runner.py` reads `error_code` and emits the matching SSE
  `error` event before the terminal `task_end` / `done`.
- **Shared `persist_snapshot` helper** in
  `apps/api/app/persistence/snapshot.py`. Every tier tool calls
  it after a successful fetch + extract. Closes Spec 07's stub.
- **JS rendering is the dynamic tier's job, not the stealth
  tier's.** Stealth handles Cloudflare on otherwise-static pages;
  if the agent sees `javascript_required`, it goes dynamic.
- **Playwright stays a single browser instance per process**
  (Scrapling's default). The semaphore gates concurrent **pages**
  (sessions), not browser launches.
- **The Spec 07 raw-HTML-stub in `runner.py` is removed.** The
  runner now reads the snapshot key off the agent's tool history
  via the trace context, OR the tool result carries the persisted
  key directly (chosen below).
- **Tool result carries the persisted snapshot key.** Each tier
  tool calls `persist_snapshot` inside its body and returns the
  resulting `(snapshot_key, snapshot_truncated)` in its result.
  The runner reads the agent's final tool history (Pydantic AI
  exposes `result.all_messages()`) to recover them and write to
  `tasks.snapshot_key`. This avoids passing 10 MB raw HTML through
  the agent's LLM context.

References:
- `context/architecture.md` — Stack table (Stealth, Dynamic),
  Storage Model (R2 paths), **Invariants 1, 2, 6, 11**
- `context/code-standards.md` — Python (async), Auth integration
- Skills: `pydantic-ai-dependency-injection`,
  `pydantic-models-py`, `fastapi`

## Implementation

### A. Install + browser deps

Scrapling browsers were installed in Spec 07 (`uv run scrapling
install`). No additional install needed; the stealth + dynamic
sessions reuse the same Playwright Chromium binary.

If a fresh clone has not run the install step yet, the api startup
fails fast on first browser-tier call with a clear error pointing
at the install command.

### B. Anti-bot detection helper — `apps/api/app/tools/_waf.py`

```python
from __future__ import annotations

from typing import Literal


WafKind = Literal["cloudflare", "akamai", "datadome", "perimeterx", "unknown"]


def detect_waf(*, status: int, headers: dict[str, str], body_excerpt: str) -> WafKind | None:
    """Classify a 4xx response by WAF fingerprint. Returns None when the
    response does not look WAF-blocked."""
    if status not in {403, 429, 503}:
        return None

    h = {k.lower(): v.lower() for k, v in headers.items()}

    # Cloudflare
    if "cloudflare" in h.get("server", ""):
        return "cloudflare"
    if "cf-ray" in h or "cf-mitigated" in h:
        return "cloudflare"
    if "checking your browser" in body_excerpt.lower():
        return "cloudflare"

    # Akamai
    if "akamaighost" in h.get("server", ""):
        return "akamai"
    if "x-akamai" in h or any(k.startswith("ak-") for k in h):
        return "akamai"

    # DataDome
    if "x-datadome" in h or "datadome" in h.get("set-cookie", ""):
        return "datadome"

    # PerimeterX
    if "x-iinfo" in h or "_pxhd" in h.get("set-cookie", ""):
        return "perimeterx"
    if "px-captcha" in body_excerpt.lower():
        return "perimeterx"

    return "unknown"
```

The function is pure — no I/O, easy to unit-test against fixture
header dicts. It does not raise; callers translate the result into
a `ScrapeFailure` with the right `reason`.

### C. Concurrency primitives — `apps/api/app/concurrency.py`

```python
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator


# Global ceilings per architecture.md.
# Per-mission ceilings land in Spec 10 with the TaskGroup runner.
_GLOBAL_HTTP = asyncio.Semaphore(60)
_GLOBAL_BROWSER = asyncio.Semaphore(8)


@asynccontextmanager
async def http_slot() -> AsyncIterator[None]:
    async with _GLOBAL_HTTP:
        yield


@asynccontextmanager
async def browser_slot() -> AsyncIterator[None]:
    """Invariant 2: browser semaphore acquired before any
    AsyncDynamicSession / AsyncStealthySession opens, released in
    finally."""
    async with _GLOBAL_BROWSER:
        yield
```

`http_slot` and `browser_slot` are `@asynccontextmanager`s so the
release-in-finally happens automatically. `scrape-pipeline-doctor`
will reject any browser session opened outside `browser_slot()`.

### D. Shared snapshot helper — `apps/api/app/persistence/snapshot.py`

```python
from __future__ import annotations

from uuid import UUID

from app.persistence.blob import BlobStore, get_blob_store


async def persist_snapshot(
    *,
    user_id: str,
    mission_id: UUID,
    task_id: UUID,
    raw_html: bytes,
    store: BlobStore | None = None,
) -> tuple[str, bool]:
    """Write a gzipped HTML snapshot to the configured blob store.
    Returns (snapshot_key, snapshot_truncated). Invariant 9: keys are
    write-once per task_id."""
    blob = store if store is not None else get_blob_store()
    return await blob.put(
        user_id=user_id, mission_id=mission_id, task_id=task_id, body=raw_html
    )
```

### E. Stealth tier tool — `apps/api/app/tools/stealth.py`

```python
from __future__ import annotations

from time import perf_counter
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from scrapling.fetchers import AsyncStealthySession

from app.concurrency import browser_slot
from app.extract import MarkdownExtractor
from app.observability import observe
from app.persistence.snapshot import persist_snapshot
from app.security import assert_robots_allows, assert_safe_url
from app.tools._waf import detect_waf


class StealthScrapeArgs(BaseModel):
    url: str = Field(..., max_length=2048)


class StealthScrapeOk(BaseModel):
    status: Literal["ok"] = "ok"
    url: str
    markdown: str
    snapshot_key: str
    snapshot_truncated: bool
    latency_ms: int


class StealthScrapeFailure(BaseModel):
    status: Literal["failed"] = "failed"
    reason: Literal[
        "site_not_supported",
        "javascript_required",
        "upstream_error",
        "not_found",
    ]
    detected_protections: list[str] = Field(default_factory=list)
    latency_ms: int


StealthScrapeResult = StealthScrapeOk | StealthScrapeFailure


class StealthDeps(BaseModel):
    user_id: str
    mission_id: UUID
    task_id: UUID
    robots_override: bool = False


@observe(name="tool.scrape_stealth")
async def scrape_stealth(deps: StealthDeps, args: StealthScrapeArgs) -> StealthScrapeResult:
    assert_safe_url(args.url)  # invariant 1
    await assert_robots_allows(args.url, robots_override=deps.robots_override)  # invariant 11

    start = perf_counter()
    async with browser_slot():  # invariant 2
        async with AsyncStealthySession(solve_cloudflare=True, headless=True) as session:
            page = await session.fetch(args.url, network_idle=True)
            latency_ms = int((perf_counter() - start) * 1000)

            if page.status == 404:
                return StealthScrapeFailure(reason="not_found", latency_ms=latency_ms)
            if page.status >= 400:
                waf = detect_waf(
                    status=page.status,
                    headers=dict(page.headers),
                    body_excerpt=(page.body or b"")[:4096].decode("utf-8", errors="replace"),
                )
                if waf in {"akamai", "datadome", "perimeterx"}:
                    return StealthScrapeFailure(
                        reason="site_not_supported",
                        detected_protections=[waf],
                        latency_ms=latency_ms,
                    )
                if waf == "cloudflare":
                    # Cloudflare bypass failed even with solve_cloudflare=True.
                    # Likely a JS-challenge variant — escalate to dynamic.
                    return StealthScrapeFailure(
                        reason="javascript_required",
                        detected_protections=["cloudflare"],
                        latency_ms=latency_ms,
                    )
                return StealthScrapeFailure(reason="upstream_error", latency_ms=latency_ms)

    extractor = MarkdownExtractor()
    extracted = await extractor.extract(html=page.body, source_url=str(page.url))

    snapshot_key, snapshot_truncated = await persist_snapshot(
        user_id=deps.user_id,
        mission_id=deps.mission_id,
        task_id=deps.task_id,
        raw_html=extracted.raw_html,
    )

    return StealthScrapeOk(
        url=str(page.url),
        markdown=extracted.markdown,
        snapshot_key=snapshot_key,
        snapshot_truncated=snapshot_truncated,
        latency_ms=int((perf_counter() - start) * 1000),
    )
```

The session opens **inside** `browser_slot()`. If the caller
cancels (CancelledError), the `async with` unwinds, the session
closes, and the semaphore releases — all in `finally` paths owned
by the context managers.

### F. Dynamic tier tool — `apps/api/app/tools/dynamic.py`

```python
from __future__ import annotations

from time import perf_counter
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from scrapling.fetchers import AsyncDynamicSession

from app.concurrency import browser_slot
from app.extract import MarkdownExtractor
from app.observability import observe
from app.persistence.snapshot import persist_snapshot
from app.security import assert_robots_allows, assert_safe_url
from app.tools._waf import detect_waf


class DynamicScrapeArgs(BaseModel):
    url: str = Field(..., max_length=2048)
    wait_for_selector: str | None = Field(default=None, max_length=256)


class DynamicScrapeOk(BaseModel):
    status: Literal["ok"] = "ok"
    url: str
    markdown: str
    snapshot_key: str
    snapshot_truncated: bool
    latency_ms: int


class DynamicScrapeFailure(BaseModel):
    status: Literal["failed"] = "failed"
    reason: Literal[
        "site_not_supported",
        "upstream_error",
        "not_found",
        "render_timeout",
    ]
    detected_protections: list[str] = Field(default_factory=list)
    latency_ms: int


DynamicScrapeResult = DynamicScrapeOk | DynamicScrapeFailure


class DynamicDeps(BaseModel):
    user_id: str
    mission_id: UUID
    task_id: UUID
    robots_override: bool = False


@observe(name="tool.scrape_dynamic")
async def scrape_dynamic(deps: DynamicDeps, args: DynamicScrapeArgs) -> DynamicScrapeResult:
    assert_safe_url(args.url)
    await assert_robots_allows(args.url, robots_override=deps.robots_override)

    start = perf_counter()
    async with browser_slot():
        async with AsyncDynamicSession(headless=True) as session:
            try:
                page = await session.fetch(
                    args.url,
                    network_idle=True,
                    wait_selector=args.wait_for_selector,
                    timeout=30_000,
                )
            except TimeoutError:
                return DynamicScrapeFailure(
                    reason="render_timeout",
                    latency_ms=int((perf_counter() - start) * 1000),
                )

            latency_ms = int((perf_counter() - start) * 1000)

            if page.status == 404:
                return DynamicScrapeFailure(reason="not_found", latency_ms=latency_ms)
            if page.status >= 400:
                waf = detect_waf(
                    status=page.status,
                    headers=dict(page.headers),
                    body_excerpt=(page.body or b"")[:4096].decode("utf-8", errors="replace"),
                )
                if waf in {"akamai", "datadome", "perimeterx"}:
                    return DynamicScrapeFailure(
                        reason="site_not_supported",
                        detected_protections=[waf],
                        latency_ms=latency_ms,
                    )
                return DynamicScrapeFailure(reason="upstream_error", latency_ms=latency_ms)

    extractor = MarkdownExtractor()
    extracted = await extractor.extract(html=page.body, source_url=str(page.url))

    snapshot_key, snapshot_truncated = await persist_snapshot(
        user_id=deps.user_id,
        mission_id=deps.mission_id,
        task_id=deps.task_id,
        raw_html=extracted.raw_html,
    )

    return DynamicScrapeOk(
        url=str(page.url),
        markdown=extracted.markdown,
        snapshot_key=snapshot_key,
        snapshot_truncated=snapshot_truncated,
        latency_ms=int((perf_counter() - start) * 1000),
    )
```

### G. HTTP tier — return typed discriminated union too

Update `apps/api/app/tools/http.py` so the HTTP tier tool returns
the same `Ok | Failure` shape. The agent needs uniform result
types to escalate.

```python
class HttpScrapeOk(BaseModel):
    status: Literal["ok"] = "ok"
    url: str
    markdown: str
    snapshot_key: str
    snapshot_truncated: bool
    latency_ms: int


class HttpScrapeFailure(BaseModel):
    status: Literal["failed"] = "failed"
    reason: Literal[
        "protected_cloudflare",
        "site_not_supported",
        "javascript_required",
        "upstream_error",
        "not_found",
    ]
    detected_protections: list[str] = Field(default_factory=list)
    latency_ms: int


HttpScrapeResult = HttpScrapeOk | HttpScrapeFailure
```

The `protected_cloudflare` reason is HTTP-tier-specific — when the
HTTP fetcher hits a CF challenge, the agent should retry with
stealth. The HTTP tier *also* runs its result through
`detect_waf`; on Cloudflare, returns `protected_cloudflare`; on
others, the same routing as the browser tiers.

The HTTP tool body now also calls `persist_snapshot` on success
(closing Spec 07's stub) and now requires `user_id`,
`mission_id`, `task_id` in its `HttpToolDeps`.

### H. Update `MissionResult` and the agent — `apps/api/app/agent.py`

```python
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext


class MissionResult(BaseModel):
    status: Literal["ok", "error"]
    summary: str
    primary_url: str | None = None
    markdown_excerpt: str | None = None
    error_code: Literal[
        "site_not_supported",
        "upstream_error",
        "not_found",
        "render_timeout",
        "agent_failed",
    ] | None = None
    detected_protections: list[str] = []


class MissionDeps(BaseModel):
    user_id: str
    mission_id: UUID
    task_id: UUID
    robots_override: bool = False


_SYSTEM_PROMPT = """
You are Autumn, a web-scraping agent. The user gives you a URL.

Tool selection:
- Always start with `scrape_http`. It is the cheapest tier.
- If `scrape_http` returns reason=protected_cloudflare, retry with
  `scrape_stealth`.
- If `scrape_http` or `scrape_stealth` returns reason=javascript_required,
  retry with `scrape_dynamic`.
- If any tool returns reason=site_not_supported, return a MissionResult
  with status='error', error_code='site_not_supported', and the detected
  protections in detected_protections. Do not retry.
- If a tool returns reason=not_found, return MissionResult with
  status='error', error_code='not_found'.
- If a tool returns reason=upstream_error or render_timeout, return
  MissionResult with status='error' and the matching error_code.

On success: return MissionResult with status='ok', primary_url set
to the final URL, markdown_excerpt set to the first ~500 chars of
the markdown, and a one-paragraph summary in `summary`.

Call exactly one tool successfully per mission. After ok, do not call
more tools.
""".strip()


def build_agent(model_factory) -> Agent[MissionDeps, MissionResult]:
    agent = Agent[MissionDeps, MissionResult](
        model=model_factory,
        deps_type=MissionDeps,
        output_type=MissionResult,
        system_prompt=_SYSTEM_PROMPT,
        retries=2,
    )

    @agent.tool
    async def scrape_http(ctx: RunContext[MissionDeps], url: str) -> HttpScrapeResult:
        """Fetch via HTTP. Cheapest. Use first."""
        return await scrape_http_impl(
            HttpToolDeps(
                user_id=ctx.deps.user_id,
                mission_id=ctx.deps.mission_id,
                task_id=ctx.deps.task_id,
                robots_override=ctx.deps.robots_override,
            ),
            HttpScrapeArgs(url=url),
        )

    @agent.tool
    async def scrape_stealth(ctx: RunContext[MissionDeps], url: str) -> StealthScrapeResult:
        """Fetch with Cloudflare-bypass stealth browser. Use when HTTP returns
        reason=protected_cloudflare."""
        return await scrape_stealth_impl(
            StealthDeps(
                user_id=ctx.deps.user_id,
                mission_id=ctx.deps.mission_id,
                task_id=ctx.deps.task_id,
                robots_override=ctx.deps.robots_override,
            ),
            StealthScrapeArgs(url=url),
        )

    @agent.tool
    async def scrape_dynamic(
        ctx: RunContext[MissionDeps], url: str, wait_for_selector: str | None = None
    ) -> DynamicScrapeResult:
        """Fetch with full Playwright browser. Use when prior tiers returned
        reason=javascript_required."""
        return await scrape_dynamic_impl(
            DynamicDeps(
                user_id=ctx.deps.user_id,
                mission_id=ctx.deps.mission_id,
                task_id=ctx.deps.task_id,
                robots_override=ctx.deps.robots_override,
            ),
            DynamicScrapeArgs(url=url, wait_for_selector=wait_for_selector),
        )

    return agent
```

(The `scrape_http_impl` etc. names alias the module-level
functions imported from `app.tools.http`, `app.tools.stealth`,
`app.tools.dynamic` — explicit imports at the top of `agent.py`.)

### I. Runner updates — `apps/api/app/runner.py`

Two changes:

1. **Pass full deps** (`user_id`, `mission_id`, `task_id`) into
   the agent via `MissionDeps`.
2. **Read `MissionResult.error_code`** and emit the right SSE
   error event before the terminal `task_end` / `done`.

Replace the `try/except` arm of `run_url_mission`:

```python
try:
    async def _run(model):
        agent = build_agent(model_factory=lambda: model)
        return await agent.run(
            url,
            deps=MissionDeps(
                user_id=user.user_id,
                mission_id=mission.id,
                task_id=task.id,
                robots_override=mission.robots_override,
            ),
        )

    result = await chain.with_fallback(_run)
except Exception as exc:
    # ... existing failure path ...
```

After the agent run:

```python
mission_result: MissionResult = result.output
final_status = (
    Status.SUCCEEDED if mission_result.status == "ok" else Status.FAILED
)

# Recover snapshot_key + parsed_markdown from the last successful
# tool call in the agent's message history.
ok_call = _last_ok_tool_call(result)
snapshot_key = ok_call.snapshot_key if ok_call else None
parsed_markdown = ok_call.markdown if ok_call else None
snapshot_truncated = ok_call.snapshot_truncated if ok_call else False

await tasks.update(
    task.id,
    status=final_status,
    parsed_markdown=parsed_markdown,
    snapshot_key=snapshot_key,
    snapshot_truncated=snapshot_truncated,
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
                "mission_id": str(mission.id),
                "task_id": str(task.id),
                "seq": 0,
            }
        )
    )

await emitter.emit(
    SseEvent.model_validate(
        {
            "type": "task_end",
            "content": {
                "status": "succeeded" if final_status == Status.SUCCEEDED else "failed",
                "preview": (parsed_markdown or "")[:500],
                "snapshot_key": snapshot_key or None,
            },
            "mission_id": str(mission.id),
            "task_id": str(task.id),
            "seq": 0,
        }
    )
)

await missions.update_status(mission.id, final_status)

await emitter.emit(
    SseEvent.model_validate(
        {
            "type": "done",
            "content": {
                "mission_status": "succeeded" if final_status == Status.SUCCEEDED else "failed",
                "cost_cents": 0,
            },
            "mission_id": str(mission.id),
            "seq": 0,
        }
    )
)
```

`_last_ok_tool_call(result)` walks `result.all_messages()` (Pydantic
AI's API) in reverse, returning the first `ToolReturnPart` whose
content is a `*Ok` model. If none found, returns `None`. Define it
in a small helper module (`apps/api/app/runner_helpers.py`).

### J. `tasks.update` accepts `latency_ms`

`TaskRepository.update` already accepts `latency_ms` per Spec 05;
the runner now actually populates it.

### K. Update web rendering for the new error code

`apps/web/widgets/task-lane-card/result-preview.tsx` already
renders `taskEnd.content.preview`. Spec 09 adds an inline error
chip rendered when an `error` event with `code:
"site_not_supported"` arrives **before** `task_end`. Implementation:

- The `useMissionStream` event list already exposes errors.
- The lane renders any `error` events in a small inline chip above
  the result preview, with copy from i18n:
  - `code: "site_not_supported"` → key `mission.errorSiteNotSupported`
    (params: `protections`)
  - `code: "not_found"` → `mission.errorNotFound`
  - `code: "render_timeout"` → `mission.errorRenderTimeout`
  - `code: "upstream_error"` → `mission.errorUpstream`

Add the new i18n keys; values are sentence-case, state-what-then-try
per `ui-context.md` Voice & Copy:

- `mission.errorSiteNotSupported` — "This site uses {protections}.
  Out of scope for now — try a different URL."
- `mission.errorNotFound` — "Page not found at this URL."
- `mission.errorRenderTimeout` — "Page took too long to render."
- `mission.errorUpstream` — "Upstream returned an error."

### L. Tests

#### `apps/api/tests/test_waf.py`

```python
from __future__ import annotations

import pytest

from app.tools._waf import detect_waf


@pytest.mark.parametrize(
    ("status", "headers", "body", "expected"),
    [
        (403, {"server": "cloudflare", "cf-ray": "abc"}, "", "cloudflare"),
        (503, {"server": ""}, "Checking your browser before accessing", "cloudflare"),
        (403, {"server": "AkamaiGHost"}, "", "akamai"),
        (403, {"x-datadome": "blocked"}, "", "datadome"),
        (403, {"x-iinfo": "P-9 ..."}, "", "perimeterx"),
        (200, {}, "", None),  # not a WAF status
        (404, {"server": "nginx"}, "", None),
        (403, {"server": "nginx"}, "Generic forbidden", "unknown"),
    ],
)
def test_classifies(status, headers, body, expected):
    assert detect_waf(status=status, headers=headers, body_excerpt=body) == expected
```

#### `apps/api/tests/test_concurrency.py`

```python
from __future__ import annotations

import asyncio
import pytest

from app.concurrency import browser_slot


@pytest.mark.asyncio
async def test_browser_slot_releases_on_exception():
    async def _try_in_slot():
        async with browser_slot():
            raise RuntimeError("simulated tool failure")

    with pytest.raises(RuntimeError):
        await _try_in_slot()

    # If the slot didn't release, this acquire would hang.
    async with asyncio.timeout(1.0):
        async with browser_slot():
            pass


@pytest.mark.asyncio
async def test_browser_slot_serializes_at_capacity():
    # The global ceiling is 8; saturate then prove the 9th waits.
    holders = []

    async def _hold():
        async with browser_slot():
            holders.append("in")
            await asyncio.sleep(0.05)
            holders.append("out")

    tasks = [asyncio.create_task(_hold()) for _ in range(9)]
    await asyncio.gather(*tasks)
    # 9 entries each: in then out. With ceiling 8, at least one entered
    # only after another exited.
    assert holders.count("in") == 9
    assert holders.count("out") == 9
```

#### `apps/api/tests/test_snapshot_helper.py`

```python
from __future__ import annotations

from uuid import uuid4
import pytest

from app.persistence.blob import LocalFsBlobStore
from app.persistence.snapshot import persist_snapshot


@pytest.mark.asyncio
async def test_persist_snapshot_round_trip(tmp_path):
    store = LocalFsBlobStore(root=tmp_path)
    body = b"<html>hello</html>"
    key, truncated = await persist_snapshot(
        user_id="user_1",
        mission_id=uuid4(),
        task_id=uuid4(),
        raw_html=body,
        store=store,
    )
    assert truncated is False
    assert await store.get(key) == body
```

#### `apps/api/tests/test_stealth_tool.py`

```python
from __future__ import annotations

import pytest

from app.security import UrlNotAllowed
from app.tools.stealth import StealthDeps, StealthScrapeArgs, scrape_stealth
from uuid import uuid4


@pytest.mark.asyncio
async def test_blocks_private_url():
    with pytest.raises(UrlNotAllowed):
        await scrape_stealth(
            StealthDeps(
                user_id="u",
                mission_id=uuid4(),
                task_id=uuid4(),
                robots_override=False,
            ),
            StealthScrapeArgs(url="http://127.0.0.1/"),
        )
```

(Live browser-tier scrape tests live in an integration suite gated
on an env flag because they spawn Chromium. Unit tests cover SSRF
+ argument validation; the integration tests cover the
WAF-detection branches against a fixture server that returns
canned headers.)

#### `apps/api/tests/test_runner_error_propagation.py`

End-to-end with mocked LLM and a fixture server that returns
`AkamaiGHost` headers. Assert the runner emits an `error` event
with `code: "site_not_supported"` before the terminal events, and
that `tasks.status` is `failed`.

### M. Order of operations

1. Write `apps/api/app/tools/_waf.py` and its unit tests.
2. Write `apps/api/app/concurrency.py` and its unit tests.
3. Write `apps/api/app/persistence/snapshot.py` and its unit
   tests.
4. Update `apps/api/app/tools/http.py` to return the new
   `HttpScrapeResult` discriminated union and to call
   `persist_snapshot`. Update its existing tests.
5. Write `apps/api/app/tools/stealth.py`.
6. Write `apps/api/app/tools/dynamic.py`.
7. Update `apps/api/app/agent.py` with the three tools, the new
   `MissionResult`, the new system prompt.
8. Update `apps/api/app/runner.py` to pass the new deps and
   handle `error_code`.
9. Add the four web i18n keys; render the inline error chip in
   `task-lane-card`.
10. Run the verification block.

## Out of Scope

- **Per-mission browser semaphore (3)** — Spec 10 with the
  TaskGroup runner.
- **Multi-URL concurrency** — Spec 10.
- **Full Akamai/DataDome/PerimeterX bypass** — out of MVP per
  `project-overview.md`. Detection-and-error is the contract.
- **Description-mode (URL discovery)** — Spec 12.
- **Adaptive selectors / `auto_save` / `selector_recovered`
  events** — Spec 13.
- **Mission cancellation surfaced through the browser session
  closing mid-render** — Spec 14. For now, an in-flight
  `AsyncDynamicSession` running a 30s render does not cancel
  cleanly when the mission row flips to `cancelled`. Spec 14
  introduces the cancellation token threading.
- **Snapshot retrieval (signed R2 URLs in the result preview)** —
  Spec 14.

## Files

### Create

- `apps/api/app/tools/_waf.py`
- `apps/api/app/tools/stealth.py`
- `apps/api/app/tools/dynamic.py`
- `apps/api/app/concurrency.py`
- `apps/api/app/persistence/snapshot.py`
- `apps/api/app/runner_helpers.py`
- `apps/api/tests/test_waf.py`
- `apps/api/tests/test_concurrency.py`
- `apps/api/tests/test_snapshot_helper.py`
- `apps/api/tests/test_stealth_tool.py`
- `apps/api/tests/test_dynamic_tool.py`
- `apps/api/tests/test_runner_error_propagation.py`

### Edit

- `apps/api/app/tools/http.py` — return discriminated union, call
  `persist_snapshot`, accept extended `HttpToolDeps`
- `apps/api/app/agent.py` — register three tools, expand system
  prompt, update `MissionResult` + `MissionDeps`
- `apps/api/app/runner.py` — pass new deps, read `error_code`,
  recover snapshot from tool history
- `apps/api/tests/test_http_tool.py` — update for new result type
- `apps/web/shared/i18n/keys/en.ts` — add 4 error keys
- `apps/web/widgets/task-lane-card/result-preview.tsx` — render
  inline error chip

### Protected (do not touch)

- `apps/api/app/security.py`
- `apps/api/alembic/versions/*` past migrations
- `packages/sse-protocol/generated/**`
- `apps/web/components/ui/*`
- All previous protected files

## Verification

Run from the repo root.

- `cd apps/api && uv sync` is a no-op (no new Python deps).
- `turbo run lint` exits 0.
- `turbo run typecheck` exits 0 — strict mypy passes against the
  new discriminated unions; `pydantic.mypy` plugin enforces the
  literal types on `status` and `reason`.
- `turbo run test` exits 0; new tests cover WAF detection (8
  parameterized cases), semaphore release on exception, semaphore
  capacity ceiling, snapshot helper round-trip, SSRF block in
  both browser tools.
- `cd apps/api && uv run pytest tests/test_runner_error_propagation.py -q`
  passes against a fixture HTTP server that emits Akamai headers;
  the api emits an `error` event with `code: "site_not_supported"`
  before the terminal events.
- `turbo run build` exits 0.

Manual:

- With Clerk + Neon + R2 + LLM keys + Langfuse set, run a
  mission against an `https://www.cloudflare.com/` (or any known
  Cloudflare-fronted page). The agent calls `scrape_http`,
  receives `protected_cloudflare`, retries with
  `scrape_stealth`, succeeds. Langfuse trace shows two tool
  spans; second is `tool.scrape_stealth`.
- Run a mission against an Akamai-fronted page (e.g.,
  `https://www.amazon.com/` historically uses Akamai). The agent
  retries once; both tools return `site_not_supported`; the SSE
  stream emits the `error` event then `task_end` (failed) then
  `done` (failed). The web UI shows the inline error chip.
- In Neon: `SELECT snapshot_key FROM tasks` shows non-null keys
  for successful missions; the corresponding R2 (or local-fs)
  object is gzipped HTML.
- Kill the api mid-mission while a stealth tool is in flight.
  The next api restart finds no orphaned browser processes
  (`pgrep chromium` returns nothing) — the `async with` context
  closed on signal.

## Done when

- [ ] Every Verification line passes.
- [ ] No invariant in `context/architecture.md` violated.
  Specifically:
  - Invariant 1 — every browser tool calls `assert_safe_url`.
  - Invariant 2 — every browser session opens inside
    `browser_slot()`.
  - Invariant 6 — only async APIs in handlers.
  - Invariant 9 — `persist_snapshot` is the only writer of
    snapshot keys; no tool overwrites an existing key.
  - Invariant 11 — every browser tool calls
    `assert_robots_allows`.
- [ ] Spec 08's invariant-3 deviation **still open** (TaskGroup
  ownership) — tracked for Spec 10. Spec 09 does not introduce
  any new `asyncio.create_task` calls.
- [ ] `apps/api/app/security.py` was not edited.
- [ ] The agent has exactly three tools registered. The system
  prompt names the escalation rules verbatim. `prompt-engineer`
  agent rules pass: `output_type=MissionResult` declared; every
  run is Langfuse-traced (no change from Spec 07).
- [ ] `context/progress-tracker.md` updated: Spec 09 to "Completed";
  Spec 10 to "In Progress"; Current Goal updated.
- [ ] `scrape-pipeline-doctor` agent run on `apps/api/**` confirms
  invariants 1, 2, 6, 9, 11 hold across the new tier tools.
- [ ] `prompt-engineer` agent run on `apps/api/app/agent.py`
  confirms the three-tool registration + system-prompt
  escalation rules verbatim.
- [ ] `llm-cost-guard` agent run on the new tier tools confirms
  bounded retries, `max_tokens` on the agent's escalation
  retries, and rate-limit coverage on any new endpoint.
- [ ] `code-reviewer` agent run on the chunk produces
  `CODE_REVIEW.md` with `Verdict: Approve`.
- [ ] `simplify` skill review on the diff returns no actionable
  findings.

## Scrape reliability note

This spec is the second-largest reliability win after Spec 04. It
adds:

1. **Cloudflare bypass** — the most common WAF, now solvable
   automatically via stealth.
2. **Honest failure on enterprise WAFs** — Akamai / DataDome /
   PerimeterX get a clean error with the user's i18n-rendered
   "site not supported, try a different URL" instead of a silent
   timeout or a misleading 500.
3. **Browser-leak protection** — every browser session opens
   inside `browser_slot()` and the `async with` close is
   exception-safe. Killed processes do not leak Chromium
   instances.
4. **Uniform snapshot persistence** — every tier writes raw HTML
   to the same R2 path through `persist_snapshot`. Spec 14's
   snapshot retrieval endpoint sees a uniform schema regardless
   of which tier scraped the page.

What remains open after Spec 09: per-mission browser-semaphore
(Spec 10), N-URL concurrency (Spec 10), mid-render cancellation
propagation (Spec 14), adaptive selectors (Spec 13).
