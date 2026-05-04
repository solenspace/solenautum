# Architecture Context

## Stack

| Layer | Technology | Role |
| --- | --- | --- |
| Web framework | Next.js 16 (Turbopack) + React 19 + TypeScript strict | UI shell, BFF proxy to api |
| UI | Tailwind 4 + shadcn/ui (Radix primitives) | Component primitives |
| Web testing | Vitest + React Testing Library | Component + hook tests |
| i18n | Custom `t(namespace, key, params?)` (flagship parity) | Translation, plurals, interpolation |
| Auth | Clerk + Postgres row-level security | JWT verification + row-level isolation |
| API framework | FastAPI + uvicorn | HTTP + SSE endpoints |
| Python runtime | Python 3.12, `uv` | Deps + virtualenv |
| Agent loop | Pydantic AI (typed `Agent[Deps, ResultType]`) | ReAct loop, tool I/O validation, retry decorators |
| LLM (primary) | OpenRouter `openai/gpt-oss-120b:free` | Reasoning + tool selection |
| LLM (fallback) | Groq `llama-3.3-70b-versatile` (free) | Outage / rate-limit fallback |
| LLM provider abstraction | `LLMProvider` interface + chain | Single switch point on 429 / 5xx |
| Search | Tavily (primary) via `SearchProvider` interface | URL discovery |
| Scraping (HTTP tier) | Scrapling `AsyncFetcher` + Crawl4AI | Fetch + LLM-ready markdown |
| Scraping (Stealth tier) | Scrapling `AsyncStealthySession` (`solve_cloudflare=True`) | Cloudflare Turnstile bypass |
| Scraping (Dynamic tier) | Scrapling `AsyncDynamicSession` (Playwright) | JS-rendered pages |
| Concurrency | `asyncio.TaskGroup` + tiered `Semaphore`s | Bounded parallel execution |
| DB | Neon Postgres + sqlmodel + alembic | Mission/task metadata, parsed markdown, selector cache |
| Blob storage | Cloudflare R2 (S3-compatible via boto3) | Gzipped HTML snapshots |
| Cache | In-memory TTL (5 min) + LRU (selectors) | Per-mission dedup, hot-path selector lookup |
| Streaming | SSE + `Last-Event-ID` + per-mission ring buffer | Resumable multiplexed streams |
| Observability | Langfuse (free tier, native Pydantic AI integration) | Trace agent runs, tool calls, costs |
| Container | Docker, base `pyd4vinci/scrapling` | Browsers preinstalled |
| Orchestrator | Turborepo + pnpm + uv (api wrapped via `package.json`) | Cross-app task graph |
| Hosting (web) | Vercel free hobby | Next.js + BFF |
| Hosting (api) | Fly.io or Render free tier | FastAPI + Playwright (ephemeral disk; durability lives in Neon + R2) |

## System Boundaries

### Web (`apps/web/`)

- `app/` — Next.js App Router pages, layouts, and BFF API routes
  (proxy only — no business logic)
- `widgets/` — composed sections: `MissionLaneStack`, `TaskLaneCard`,
  `MissionSidebar`, `UrlApprovalGate`
- `features/run-mission/` — SSE multiplex hook with `Last-Event-ID`
  resume, URL-mode mission form
- `features/discover-urls/` — description-mode form and URL approval
  gate UI
- `features/auth/` — Clerk integration boundary (sign-in / sign-up /
  protected layout)
- `entities/` — typed domain models: mission, task, saved selector,
  SSE event
- `shared/` — i18n, fetchers, SSE parser, command palette, keyboard
  shortcut registry, utilities
- `components/ui/` — shadcn primitives (protected; modify only via the
  shadcn CLI)

### API (`apps/api/app/`)

- `main.py` — FastAPI factory only; mounts routers and lifecycle
  handlers
- `routes.py` — HTTP and SSE endpoints; pydantic validation only,
  no business logic
- `security.py` — Clerk JWT verification (JWKS), SSRF guard, optional
  URL allow-list, per-user rate limiter, robots.txt honor logic
  (load-bearing; protected)
- `agent.py` — Pydantic AI `Agent` build, tool registration, retry
  decorators
- `llm/` — `LLMProvider` interface, OpenRouter and Groq adapters,
  fallback chain triggered only on 429 / 5xx
- `tools/http.py` — Scrapling `AsyncFetcher` + Crawl4AI tools
- `tools/stealth.py` — Scrapling `AsyncStealthySession` tools
- `tools/dynamic.py` — Scrapling `AsyncDynamicSession` tools
- `tools/search.py` — `SearchProvider` interface + Tavily implementation
- `concurrency.py` — `TaskGroup` runner, tiered semaphores, mission
  lifecycle
- `sse.py` — schema-validated event emitter, per-mission ring buffer,
  `Last-Event-ID` resume handler
- `persistence/models.py` — sqlmodel definitions for `users`,
  `missions`, `tasks`, `saved_selectors`
- `persistence/repository.py` — repository pattern, ownership enforcement
- `persistence/blob.py` — R2 adapter (boto3, S3-compatible)
- `persistence/markdown.py` — Crawl4AI output normalization for
  storage
- `observability.py` — Langfuse tracer init, trace metadata propagation
- `jobs/reaper.py` — orphan-mission cleanup (timeout `pending` rows
  after 1 hour)
- `config.py`, `logging.py` — env loading, structured logging

### Shared (`packages/sse-protocol/`)

- `schema.json` — JSON Schema for the SSE event shape (single source
  of truth)
- `generated/types.ts` — generated TypeScript types
- `generated/models.py` — generated pydantic v2 models
- Generation script runs in CI; generated files are protected

## Storage Model

### Neon Postgres (metadata + parsed markdown)

- **`users`** — synced from Clerk via webhook. Columns: `id` (Clerk
  user_id), `email`, `created_at`.
- **`missions`** — `id` (UUIDv4), `user_id`, `prompt`, `mode`
  (`url` | `description`), `status` (`pending` | `running` |
  `succeeded` | `failed` | `cancelled`), `cost_cents`, `created_at`,
  `finished_at`. Row-level security policy: `user_id =
  auth.user_id()`.
- **`tasks`** — `id` (UUIDv4), `mission_id`, `url`, `tier_used`
  (`http` | `stealth` | `dynamic`), `status`, `latency_ms`,
  `parsed_markdown` (text), `snapshot_key` (R2 path), `selector_cache_id`
  (nullable FK), `started_at`, `finished_at`. RLS via join to
  `missions.user_id`.
- **`saved_selectors`** — `id` (UUIDv4), `domain`, `purpose`, `payload`
  (jsonb — Scrapling adaptive snapshot), `hit_count`, `last_used_at`.
  Covering index on `(domain, purpose)`. Scoped per deployment, not
  per user.
- All foreign keys are `ON DELETE CASCADE` from mission down to task.
- Migrations managed by alembic; one migration per Unit that touches
  schema.

### Cloudflare R2 (raw HTML snapshots)

- Bucket: `autumn-snapshots`
- Object key: `{user_id}/{mission_id}/{task_id}.html.gz`
- Max object size: 10 MB; oversize bodies are truncated and the row
  is flagged with `snapshot_truncated = true`.
- Retrieval: signed URLs with 1-hour TTL via boto3 `generate_presigned_url`.
- 30-day lifecycle deletion on snapshots; parsed markdown in Neon
  is retained until user deletion.

### In-memory caches (per api process)

- **Fetch cache** — keyed by `(url, tier, ua_bucket)`, 5-minute TTL,
  bounded at 256 entries; evicts on size cap.
- **Selector LRU** — keyed by `(domain, purpose)`, 1000 entries;
  warmed on Neon read, evicted least-recently-used.
- **SSE ring buffer** — keyed by `mission_id`, last 200 events with
  monotonic `seq`. Evicted when mission terminates plus a 60-second
  grace window.

### Concurrency-shared state

- Per-mission state flows through `asyncio.Queue` instances into the
  SSE emitter. Mutable globals are forbidden.

## Auth and Access Model

- Clerk handles sign-in/sign-up on the web side; the BFF proxies the
  Clerk JWT to the api on every request.
- The api verifies the JWT against Clerk's JWKS; `user_id` is
  extracted into a request-scoped context (`contextvars`).
- Mission and task ownership is enforced at the **repository layer**
  on every read and mutation; Postgres RLS is the defense-in-depth
  backstop. The client's claimed `user_id` is never trusted.
- `prompt` is validated as 1–2000 characters (flagship parity).
- `AUTUMN_URL_ALLOWLIST` env flag — opt-in domain allow-list. Off by
  default in dev; recommended on for any hosted deployment.
- Per-user rate limit at the api gateway: 60 requests / minute,
  1000 requests / day. Keyed on `user_id`.
- Clerk users sync into Neon `users` via webhook; the webhook itself
  is verified against Clerk's signing secret.
- `robots.txt` is honored by default. A per-mission override flag
  exists, but every override emits a logged event attributed to the
  user_id and the URL pattern.

> **Pooler caveat**: RLS via `SET LOCAL app.user_id` runs inside a
> transaction. Neon's PgBouncer pool in transaction mode is supposed
> to preserve transaction-scoped GUCs, but Neon's docs explicitly
> forbid session-level `SET`/`RESET`. Spec 05 includes an empirical
> verification step against a Neon dev branch: insert a row as user_a,
> switch to user_b, assert the row is hidden. If the pooler swallows
> the GUC, fall back to using `DATABASE_URL_UNPOOLED` for the runtime
> app session. The repository layer's ownership checks remain the
> primary enforcement; RLS is defense-in-depth either way.

## Invariants

These rules are non-negotiable. Every code change must preserve them.

1. **SSRF guard runs on every URL** before any fetcher tier touches
   the network. The guard validates scheme, resolves hostname → IP,
   and blocks private CIDR ranges (127/8, 10/8, 172.16/12,
   192.168/16, 169.254/16). No code path bypasses it.
2. **Browser-tier semaphore** is acquired before any
   `AsyncDynamicSession` or `AsyncStealthySession` page is opened
   and released in a `finally` block. Browser leaks are a hard
   failure, not a warning.
3. **A mission's `TaskGroup` owns all of its tasks.** No task spawns
   detached `asyncio.create_task()` work that outlives the group.
4. **SSE events for one mission serialize through one queue.**
   Multiple emitters never write to the same response stream
   concurrently. Every emitted event also lands in the per-mission
   ring buffer with a monotonic `seq`.
5. **Every task emits exactly one terminal event** (`task_end` with
   final status, or `error`). Missing terminals are bugs to fix,
   not states to recover from.
6. **Request handlers do not block the event loop.** Only
   `Async*` Scrapling APIs and async Crawl4AI calls run inside
   handlers; synchronous fetches are forbidden in the request path.
7. **Mission and task rows persist to Neon before the first SSE
   event is emitted** for that entity. The DB is the source of
   truth; the stream is a projection.
8. **Adaptive selectors namespace by `(domain, selector_purpose)`.**
   A selector saved for site A is never reused for site B even if
   the CSS path matches by coincidence.
9. **Snapshot store is write-once per `task_id`.** Re-runs create
   new task rows with new ids; they never overwrite snapshots.
10. **No tool call is made without an active mission row in
    `running` status owned by an authenticated user.** Orphaned or
    cancelled tool calls are dropped before any network egress.
11. **`robots.txt` is honored on every URL** unless the mission row
    carries a user-attributed override flag. Every override emits
    an event into the structured log with `user_id` and URL pattern.
12. **LLM provider switch (primary → fallback) triggers only on
    rate-limit (HTTP 429) or 5xx**, never on malformed tool args.
    Tool-arg failures are retried via Pydantic AI retry decorators
    on the same provider.
