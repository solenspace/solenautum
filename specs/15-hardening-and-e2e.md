# 15 — hardening-and-e2e

## Goal

Final spec. Take Autumn from "feature-complete in dev" to
"deployable on Fly.io and Vercel with end-to-end coverage."
Replace stdlib logging with `structlog` so every line is JSON
with `mission_id` / `task_id` propagation. Split `/health` into
liveness + readiness probes that cover Postgres, R2, and Clerk
JWKS. Ship a `Dockerfile` based on `pyd4vinci/scrapling` (the
official image with Scrapling + Playwright browsers
preinstalled). Add Playwright web e2e tests covering a 10-URL
mission with forced SSE disconnect mid-stream, and pytest api
integration tests covering the same flow without a browser.
Commit `fly.toml` for the api and the Vercel project config for
the web, plus a one-file ops runbook.

## Dependencies

- All prior specs (01–14)

## Design Decisions

### Structured logging

- **`structlog` with JSON output.** Replace every
  `logging.getLogger(__name__)` call with
  `structlog.get_logger()`. Configure once at startup
  (`app/logging.py`):
  - `JSONRenderer` for production
  - `ConsoleRenderer` (pretty) for `LOG_FORMAT=console`
- **Context binding via `contextvars`** so `mission_id` and
  `task_id` propagate automatically through async boundaries.
  At `_run_task` start: `structlog.contextvars.bind_contextvars(
  mission_id=str(mission.id), task_id=str(task.id))`.
- **Every emitted log line includes**: `level`, `ts` (ISO 8601
  UTC), `event` (the message), `mission_id`/`task_id` if set,
  plus any kwargs from the call site.
- **Log levels**: `INFO` for state transitions; `WARNING` for
  recoverable conditions (provider switch, selector eviction);
  `ERROR` for unhandled exceptions.
- **No emoji or color codes** in JSON output.
- **Uvicorn access logs are disabled** (too noisy in JSON);
  request IDs come from FastAPI middleware.

### Liveness + readiness probes

- **`GET /health`** — always returns 200 if the process is
  responsive. Fly.io and Render's "is the container alive"
  check.
- **`GET /health/ready`** — checks the three downstream
  dependencies:
  1. Postgres: `SELECT 1` against the unpooled URL with a
     500ms timeout.
  2. R2: `HEAD` on the configured bucket via boto3 with 1s
     timeout.
  3. Clerk JWKS: `GET https://api.clerk.com/.well-known/jwks.json`
     with 1s timeout.
  Returns `{ok: true, checks: {postgres: "ok", r2: "ok",
  clerk: "ok"}}` when all three pass. Returns `503` with the
  failing component(s) named otherwise. Fly.io's
  `[[services.checks]]` points at `/health/ready`.
- **Failure budget**: any one downstream returning a soft
  failure (timeout < 1s) is reported but does not flap the
  container. Hard failures (DNS, refused connection) flag the
  readiness as not-ready, which routes new traffic away until
  the dependency recovers.

### Docker image

- **Base**: `pyd4vinci/scrapling:latest` (or pinned to a
  specific tag). Ships Scrapling + Playwright Chromium, saving
  ~5 minutes of build time.
- **Multi-stage** is unnecessary because `uv` produces a single
  virtualenv we copy in.
- **Build steps**:
  1. Install uv (one curl).
  2. Copy `pyproject.toml`, `uv.lock`.
  3. `uv sync --frozen --no-dev`.
  4. Copy app code.
  5. `CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`.
- **Image size target**: under 1.2 GB compressed (the Scrapling
  base is ~900 MB before our deps). If we exceed, prune by
  switching to `pyd4vinci/scrapling:slim` or installing
  Playwright browsers ourselves with `--no-deps`.
- **Container runs as non-root** (UID 1000); `WORKDIR /app`.
  No SSH, no shell tools beyond what the base image provides.

### Fly.io configuration

- `apps/api/fly.toml`:

  ```toml
  app = "autumn-api"
  primary_region = "iad"

  [build]
    dockerfile = "Dockerfile"

  [env]
    LOG_FORMAT = "json"

  [http_service]
    internal_port = 8000
    force_https = true
    auto_stop_machines = "stop"
    auto_start_machines = true
    min_machines_running = 0

    [[http_service.checks]]
      grace_period = "10s"
      interval = "30s"
      method = "get"
      path = "/health/ready"
      protocol = "http"
      timeout = "5s"

  [[vm]]
    cpu_kind = "shared"
    cpus = 1
    memory_mb = 1024
  ```

- Secrets injected via `fly secrets set` (Clerk, OpenRouter,
  Groq, Tavily, Langfuse, R2 credentials, `DATABASE_URL`,
  `DATABASE_URL_UNPOOLED`).
- **Single-region for MVP.** Multi-region adds latency
  trade-offs and Postgres replication concerns out of scope.

### Vercel configuration

- `apps/web/vercel.json`:

  ```json
  {
    "buildCommand": "cd ../.. && pnpm turbo run build --filter=@autumn/web",
    "outputDirectory": ".next",
    "installCommand": "cd ../.. && pnpm install --frozen-lockfile",
    "framework": "nextjs"
  }
  ```

- Env vars (Clerk publishable + secret keys, `AUTUMN_API_URL`,
  Clerk webhook routing) configured via the Vercel dashboard
  (or `vercel env`). The repo's `.env.example` is the
  documentation.
- Vercel project root set to `apps/web/`; the build command
  reaches up to the monorepo root for the install + Turbo
  cache.

### End-to-end coverage

- **Playwright web e2e**:
  `apps/web/tests/e2e/mission-flow.spec.ts` — boots the dev
  servers (Vercel preview build of web + a local api with
  fixture credentials), signs in via Clerk's test mode, runs
  a 5-URL mission against a fixture HTTP server (the
  Playwright `request.route` handler returns canned HTML),
  asserts the slide-over renders 5 lanes, asserts terminal
  events fire, force-disconnects the SSE midstream
  (`browserContext.setOffline(true)` then `false` — this is the
  canonical Playwright API; `page.context().setOffline()` was a
  legacy alias that no longer ships) and asserts replay picks up.
- **pytest api integration**:
  `apps/api/tests/integration/test_mission_lifecycle.py` —
  spawns FastAPI via `httpx.ASGITransport`; mocks LLM,
  Tavily, Scrapling against a fixture HTTPServer; runs the
  full URL-mode + description-mode flows; asserts the SSE
  event sequence + DB state transitions.
- **Run cadence**: not on every PR (slow). Nightly cron in CI
  + on-demand via `pnpm e2e`. PR gate is the unit test suite.

### Visual verification via the Playwright MCP

For ad-hoc visual checks during development — the kind of "did
this UI change look right?" question that doesn't justify a new
checked-in test — use the **Playwright MCP**
(`@playwright/mcp`). The MCP exposes browser automation as Claude
Code tool calls (navigate, click, type, screenshot, wait, snapshot
the accessibility tree). The implementer can ask the agent to
"open `/missions`, sign in, submit a 5-URL mission, screenshot
the slide-over after the third `task_end` event" and the agent
drives a real browser to verify. No throwaway test file.

The Playwright MCP **does not replace** the checked-in
`mission-flow.spec.ts`. The spec file is the CI regression
baseline; the MCP is the iteration-loop accelerator. Use both:

| Use case | Tool |
|---|---|
| CI regression on every release | `mission-flow.spec.ts` (Playwright test runner) |
| "Does this UI render correctly right now?" | Playwright MCP (interactive) |
| Visual comparison across two states | Playwright MCP (screenshot tool) |
| First-time verification of a freshly-built feature | Playwright MCP, then graduate the assertion to `mission-flow.spec.ts` if it's worth catching as a regression |

Install at `SETUP.md`'s MCP section. The MCP runs locally with no
auth; first install is `claude mcp add playwright npx @playwright/mcp@latest`.

**Capability limits to know**: the MCP does not store sessions
across runs (no persistent fixtures), does not perform pixel-
diff regression (only on-demand screenshots), and uses headed
browsers by default. For pixel-diff and persistent regression,
the checked-in spec file is the only path.

### Logging migration touchpoints

- Every `import logging` becomes
  `import structlog`.
- Every `log = logging.getLogger(__name__)` becomes
  `log = structlog.get_logger()`.
- Every `log.info("...", extra={...})` becomes
  `log.info("...", **{...})`.
- The `logging.exception` calls keep their signature;
  structlog's `ExceptionRenderer` formats stack traces inline
  in the JSON output.
- The `app/logging.py` module owns the configuration; nothing
  else imports `logging` directly.

### Ops runbook

- One file: `RUNBOOK.md` at repo root.
- Sections:
  1. **First-time deploy** — `fly launch` for api, Vercel
     import for web, secrets list.
  2. **Deploys** — `fly deploy --config apps/api/fly.toml` for
     api; Vercel auto-deploys web on push to main.
  3. **Migration runbook** — `fly ssh console -C "uv run alembic
     upgrade head"`. Down-migration warnings: never edit a
     past migration.
  4. **Rollback** — `fly releases rollback` for api; Vercel's
     dashboard for web.
  5. **Troubleshooting** — common failure modes (Clerk webhook
     signature drift, Tavily rate-limit, Postgres connection
     count saturation), what the logs look like, what to do.
  6. **Observability** — Langfuse dashboard URL, Fly.io logs
     `fly logs --app autumn-api`.

References:
- `context/architecture.md` — Stack table (hosting), all 12
  invariants
- `context/code-standards.md` — Observability, Python
- `context/ai-workflow-rules.md` — Verification gates

## Implementation

### A. structlog migration

#### `apps/api/pyproject.toml`

```bash
cd apps/api
uv add structlog
```

#### `apps/api/app/logging.py`

```python
from __future__ import annotations

import logging
import sys

import structlog

from app.config import settings


def configure_logging() -> None:
    log_format = (
        "console" if settings.log_format == "console" else "json"
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if log_format == "console":
        renderer = structlog.dev.ConsoleRenderer(colors=False)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Silence uvicorn access logs (covered by FastAPI middleware below).
    logging.getLogger("uvicorn.access").disabled = True
```

`settings.log_format` is a new env-driven field defaulting to
`"json"`.

#### `apps/api/app/main.py`

```python
from app.logging import configure_logging

configure_logging()
```

Called at module import time, before FastAPI app construction.

#### Per-task context binding — runner update

`apps/api/app/runner.py`:

```python
import structlog

log = structlog.get_logger()


class MissionRunner:
    async def _run_task(self, task: Task) -> None:
        with structlog.contextvars.bound_contextvars(
            mission_id=str(self._mission.id),
            task_id=str(task.id),
        ):
            # ... existing body ...
```

Every log line emitted from inside that block carries
`mission_id` and `task_id` automatically.

#### Migration sweep

A grep + replace pass:

```bash
rg -l "import logging" apps/api/app | xargs sed -i '' \
  -e 's/import logging/import structlog/g' \
  -e 's/logging.getLogger(__name__)/structlog.get_logger()/g'
```

Then a manual review for `extra={...}` call sites — convert to
`**{...}` per structlog's idiom.

### B. /health and /health/ready

#### `apps/api/app/routes.py`

```python
import asyncio

import httpx
from sqlalchemy import text

from app.persistence.db import _engine
from app.persistence.blob import get_blob_store


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready() -> dict[str, object]:
    checks: dict[str, str] = {}
    ok = True

    # Postgres
    try:
        async with asyncio.timeout(0.5):
            async with _engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "down"
        ok = False

    # R2
    try:
        async with asyncio.timeout(1.0):
            blob = get_blob_store()
            # boto3 head_bucket is sync; run in a thread.
            await asyncio.to_thread(_head_bucket, blob)
        checks["r2"] = "ok"
    except Exception:
        checks["r2"] = "down"
        ok = False

    # Clerk JWKS
    try:
        async with asyncio.timeout(1.0):
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.clerk.com/.well-known/jwks.json"
                )
                response.raise_for_status()
        checks["clerk"] = "ok"
    except Exception:
        checks["clerk"] = "down"
        ok = False

    if not ok:
        raise HTTPException(503, detail={"checks": checks})
    return {"ok": True, "checks": checks}


def _head_bucket(blob) -> None:
    if hasattr(blob, "_client"):
        blob._client.head_bucket(Bucket=blob._client.meta.config.region_name)  # type: ignore
```

The `_head_bucket` helper is intentionally lenient — for the
`LocalFsBlobStore` it falls through to a stat() check on the
data dir.

### C. Dockerfile

`apps/api/Dockerfile`:

```dockerfile
FROM pyd4vinci/scrapling:latest

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

# Layer caching: deps before code.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

`--workers 1` because the lifespan TaskGroup is process-local;
multi-worker requires inter-process coordination that's out of
scope for MVP.

### D. fly.toml + Vercel config

`apps/api/fly.toml`: see Design Decisions section.
`apps/web/vercel.json`: see Design Decisions section.

### E. Playwright e2e tests

#### Install

```bash
pnpm --filter @autumn/web add -D @playwright/test
pnpm --filter @autumn/web exec playwright install chromium
```

#### `apps/web/playwright.config.ts`

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  use: {
    baseURL: process.env.AUTUMN_E2E_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
  },
  webServer: {
    command: "pnpm dev",
    port: 3000,
    reuseExistingServer: !process.env.CI,
  },
});
```

#### `apps/web/tests/e2e/mission-flow.spec.ts`

```ts
import { test, expect } from "@playwright/test";


test("URL-mode 5-URL mission renders end-to-end", async ({ page }) => {
  await page.goto("/sign-in");
  // Clerk testing token flow
  await page.locator('[data-testid="clerk-test-sign-in"]').click();
  await expect(page).toHaveURL("/missions");

  // Fixture URLs served by the test server (not real internet)
  const fixtureUrls = Array.from({ length: 5 }, (_, i) =>
    `http://127.0.0.1:9999/page-${i}`
  );

  // Open multi-URL slide-over
  await page.keyboard.press("Meta+Shift+N");
  const textarea = page.getByRole("textbox", { name: /multi/i });
  await textarea.fill(fixtureUrls.join("\n"));
  await textarea.press("Meta+Enter");

  // Slide-over opens with the stack
  await expect(page.getByRole("log")).toBeVisible();

  // 5 task lanes appear
  await expect(page.locator('li[data-status]')).toHaveCount(5, { timeout: 30_000 });

  // All terminal
  await expect(page.locator('li[data-status="succeeded"]')).toHaveCount(5, {
    timeout: 60_000,
  });
});


test("forced disconnect mid-stream resumes via Last-Event-ID", async ({ page, context }) => {
  // ... similar setup ...
  await context.setOffline(true);
  await page.waitForTimeout(2000);
  await context.setOffline(false);
  // Reconnecting chip appears then clears; events resume
  await expect(page.getByText("Reconnecting…")).toBeHidden({ timeout: 10_000 });
  await expect(page.locator('li[data-status="succeeded"]')).toHaveCount(5);
});
```

The Clerk testing flow uses Clerk's test-mode tokens; the fixture
HTTP server (port 9999) is started by a `globalSetup` script that
runs an `http.createServer` returning canned HTML for any path.

### F. pytest api integration

#### `apps/api/tests/integration/test_mission_lifecycle.py`

```python
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.asyncio
@pytest.mark.integration
async def test_url_mode_5_url_mission_e2e(
    fixture_server,  # pytest fixture serving canned HTML
    mocked_llm,      # pydantic-ai test model
    clerk_test_jwt,  # forged Clerk JWT for test
):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        response = await client.post(
            "http://test/missions",
            json={"mode": "url", "urls": [f"{fixture_server}/page-{i}" for i in range(5)]},
            headers={"Authorization": f"Bearer {clerk_test_jwt}"},
        )
        assert response.status_code == 202
        mission_id = response.json()["mission_id"]

        # Stream the SSE
        async with client.stream(
            "GET", f"http://test/run-mission/{mission_id}/stream",
            headers={"Authorization": f"Bearer {clerk_test_jwt}"},
        ) as stream:
            events = []
            async for line in stream.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

        # 5 task_start, 5 task_end, 1 done
        types = [e["type"] for e in events]
        assert types.count("task_start") == 5
        assert types.count("task_end") == 5
        assert types.count("done") == 1
```

The `fixture_server`, `mocked_llm`, `clerk_test_jwt` fixtures
live in `apps/api/tests/integration/conftest.py`.

### G. RUNBOOK.md

A single file at repo root, six sections per the design above.
~150 lines max — every section is operationally necessary.

```markdown
# Autumn Operations Runbook

## First-time deploy
- ...

## Deploys
- ...

## Migrations
- ...

## Rollback
- ...

## Troubleshooting
- ...

## Observability
- ...
```

### H. Order of operations

1. `cd apps/api && uv add structlog`. Build `app/logging.py`,
   wire `configure_logging()` in `main.py`.
2. Sweep stdlib `logging` calls; convert to `structlog`.
3. Add `structlog.contextvars.bound_contextvars` to
   `_run_task`.
4. Build `/health` and `/health/ready` endpoints + dependency
   check helpers.
5. Write `apps/api/Dockerfile`. Build locally (`docker build
   -t autumn-api apps/api`) — confirm under 1.2 GB.
6. Write `apps/api/fly.toml`. Run `fly launch --copy-config
   --no-deploy` to test parsing.
7. Write `apps/web/vercel.json`.
8. Install Playwright; write `mission-flow.spec.ts`; verify
   `pnpm exec playwright test` runs locally.
9. Write `apps/api/tests/integration/test_mission_lifecycle.py`
   with the fixture conftest.
10. Write `RUNBOOK.md`.
11. Run the verification block.

## Out of Scope

- **Multi-region deployment** — single-region for MVP.
- **Datadog / Honeycomb integration** — Langfuse + structured
  JSON logs to Fly.io's log stream is enough for MVP.
- **Auto-scaling beyond `min_machines_running = 0`** — Fly.io
  cold-starts on first request after idle; acceptable for
  the demo.
- **Backup / point-in-time recovery automation** — Neon's free
  tier ships PITR; documented in RUNBOOK but not wired to a
  cron job.
- **CI/CD pipeline (GitHub Actions)** — out of scope; Spec 03's
  hooks are the local gate. CI mirroring is a follow-up if
  team grows.
- **Per-tenant rate limiting beyond Spec 04's gateway limits** —
  the in-memory limiter is single-process; multi-instance
  scale needs Redis. Documented in RUNBOOK as a known scaling
  edge.
- **Container image signing / SLSA provenance** — defer until
  paying customers exist.

## Files

### Create

- `apps/api/Dockerfile`
- `apps/api/fly.toml`
- `apps/api/.dockerignore`
- `apps/api/app/logging.py`
- `apps/api/tests/integration/__init__.py`
- `apps/api/tests/integration/conftest.py`
- `apps/api/tests/integration/test_mission_lifecycle.py`
- `apps/web/vercel.json`
- `apps/web/playwright.config.ts`
- `apps/web/tests/e2e/mission-flow.spec.ts`
- `apps/web/tests/e2e/global-setup.ts`
- `RUNBOOK.md`

### Edit

- `apps/api/pyproject.toml` — add `structlog`
- `apps/api/app/config.py` — add `log_format` field
- `apps/api/app/main.py` — call `configure_logging()`
- `apps/api/app/runner.py` — bind contextvars per task
- `apps/api/app/routes.py` — add `/health/ready`
- `apps/api/app/observability.py` — switch to structlog
- All `app/**/*.py` files using stdlib `logging` — convert to
  structlog (sweep)
- `apps/web/package.json` — add `@playwright/test` dev dep
- `package.json` — add `e2e` script: `turbo run e2e`
- `turbo.json` — add `e2e` task with `cache: false`,
  `dependsOn: ["build"]`

### Protected (do not touch)

- `apps/api/app/security.py`
- Past alembic migrations
- `packages/sse-protocol/generated/**`
- `apps/web/components/ui/*`
- All previous protected files

## Verification

Run from the repo root.

- `pnpm install` exits 0; `@playwright/test` resolves.
- `cd apps/api && uv sync` resolves `structlog`.
- `turbo run lint` exits 0.
- `turbo run typecheck` exits 0.
- `turbo run test` exits 0.
- `turbo run build` exits 0.
- `docker build -t autumn-api apps/api` succeeds; image size
  reported by `docker images autumn-api` is under 1.2 GB.
- `cd apps/api && uv run uvicorn app.main:app --port 8000 &`,
  then `curl http://localhost:8000/health` returns
  `{"status":"ok"}` and `curl http://localhost:8000/health/ready`
  returns 200 with all three checks `ok` (assuming env is set).
- `LOG_FORMAT=json uv run uvicorn app.main:app` emits JSON logs.
- `pnpm e2e` runs the Playwright suite to completion; the
  mission-flow spec passes.
- `cd apps/api && uv run pytest tests/integration -m integration`
  passes.
- `fly launch --copy-config --no-deploy` parses `fly.toml`
  cleanly (no actual deploy).

Manual:

- Push to a Vercel preview branch; preview URL boots and
  serves `/sign-in` correctly.
- `fly deploy --config apps/api/fly.toml` to a staging app;
  `/health/ready` returns 200; submit a mission; observe JSON
  logs in `fly logs` with `mission_id` propagated on every line.
- Disconnect Postgres (drop a Neon branch) — `/health/ready`
  returns 503 with `postgres: "down"`. Restore — `/health/ready`
  recovers within 30s.

## Done when

- [ ] Every Verification line passes.
- [ ] No invariant in `context/architecture.md` violated.
- [ ] `apps/api/app/security.py` was not edited.
- [ ] No `print()` calls anywhere (`grep -R 'print(' apps/api/app`
  returns nothing outside intentional CLI scripts).
- [ ] No `import logging` calls remain in `apps/api/app/**`
  outside `app/logging.py` itself.
- [ ] `RUNBOOK.md` covers all six sections.
- [ ] `context/progress-tracker.md` updated: Spec 15 to
  "Completed"; phase changes from "specs draft" to "shipping".
- [ ] `scrape-pipeline-doctor` agent run on `apps/api/**` (final
  pass) finds zero violations.
- [ ] `sse-streaming-reviewer` agent run on `apps/api/app/sse.py`
  + `packages/sse-protocol/**` (final pass) finds zero violations.
- [ ] `fsd-architect` agent run on `apps/web/**` (final pass)
  finds zero layer violations.
- [ ] `code-reviewer` agent run on the full release diff
  produces `CODE_REVIEW.md` with `Verdict: Approve` (release
  gate).
- [ ] `simplify` skill review on the diff returns no actionable
  findings.

## Scrape reliability note

This spec is the boring one — no new product features, all
operational. Reliability impact:

1. **Failures become diagnosable.** JSON logs with
   `mission_id` / `task_id` mean a single grep recovers every
   line related to a stuck mission. Stdlib's stringly-typed
   logging required visual scanning.
2. **Container orchestrators see real readiness.** Fly.io
   stops routing traffic to a replica with a degraded
   downstream; `/health/ready` is the truth.
3. **Deploy mistakes are bounded.** The Docker image runs
   identically in dev and prod; the `pyd4vinci/scrapling`
   base eliminates "browsers not installed" as a class of
   prod incidents.
4. **End-to-end coverage exists.** A Playwright run before each
   release exercises the slide-over → SSE → cancel →
   resume flow that no unit test can fully simulate. CI runs
   it nightly; humans run it before deploys.
5. **Rollback is documented.** RUNBOOK has the exact `fly
   releases rollback` invocation and the Vercel-dashboard
   procedure. New operators do not need tribal knowledge.

After Spec 15: Autumn is feature-complete and shippable. The
next phase is real-world scale, observability tuning, and the
next product question — none of which are speculated about
here.
