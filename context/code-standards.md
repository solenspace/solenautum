# Code Standards

> Auto-loaded skills accelerate edits and reviews:
> `next-best-practices` and `vercel-composition-patterns` (Vercel) for
> the web app; `fastapi`, `pydantic-models-py`, and
> `pydantic-ai-dependency-injection` for the api; user-level
> `react-architecture` and `simplify` for senior-grade conventions and
> clean-code review. This file remains the source of truth — skills are
> fast-paths, not replacements.

## General

- Keep modules small and single-purpose. A file that owns more than
  one responsibility is a refactor candidate.
- Fix root causes; do not layer workarounds. If a bug points at a
  missing invariant in `architecture.md`, update the invariant first.
- Do not mix unrelated concerns in one component, route, or unit.
- Trust internal code and framework guarantees. Validate only at
  system boundaries (user input, external APIs, env config).
- Three similar lines beats a premature abstraction. Do not design
  for hypothetical future requirements.

## TypeScript (web)

- Strict mode is required project-wide; `tsc --strict` must pass in
  CI.
- No `any`. Use explicit interfaces or narrowly scoped types. Where a
  third-party library leaks `any`, wrap it in a typed adapter at the
  boundary.
- Validate unknown external input at system boundaries with `zod`.
  BFF API routes parse the request body before any logic runs.
- Exported domain types live in `entities/`. SSE event types are
  imported from the generated module in `packages/sse-protocol/` —
  never duplicated locally.
- No barrel files in feature folders; import from concrete modules.
- React components that use hooks declare `'use client'` on line one.

## Python (api)

- `ruff` (lint + format) and `mypy --strict` must pass in CI. No
  `# type: ignore` without an inline justification comment.
- `from __future__ import annotations` at the top of every module.
- Pydantic v2 for every I/O boundary: request bodies, tool inputs,
  tool outputs, persistence DTOs. Pydantic AI tool functions return
  pydantic models, not dicts.
- No bare `except:`; catch the narrowest applicable exception class.
- Async/await throughout the request path. Never call `asyncio.run`
  inside a handler. Synchronous Scrapling and Crawl4AI calls are
  forbidden in handlers (invariant 6).
- Database access goes through the repository layer; raw SQL only
  appears in alembic migrations.
- Inject dependencies (LLM provider, search provider, blob store)
  via FastAPI's `Depends`. Concrete implementations are wired at
  startup; tests substitute fakes.

## Next.js (web)

- Default to server components. `'use client'` only when interactivity
  requires browser APIs.
- Route handlers in `app/` are BFF proxies only. They validate the
  request, forward the Clerk JWT, and stream the response. Business
  logic is forbidden here.
- SSE consumption goes through the single
  `features/run-mission/use-mission-stream.ts` hook. Reach for
  `EventSource` directly only inside this hook.
- Loading and error states are first-class: every async UI surface
  ships a skeleton matching final layout shape and an error state
  with a per-URL retry CTA.

## FastAPI (api)

- Pydantic models live in `routes.py` (or its sibling DTO module);
  business logic lives in `agent.py`, `concurrency.py`, and the
  tool modules.
- Route bodies follow this order: validate → auth → rate-limit →
  invariant checks → dispatch. Skipping a step is a code-review
  blocker.
- Endpoints return typed responses; SSE endpoints emit events that
  validate against `packages/sse-protocol/`'s pydantic models.
- Cancellation is structured: every long-running coroutine respects
  `asyncio.CancelledError` and propagates it through the
  `TaskGroup`.

## Auth integration

- Clerk JWT is verified via Clerk's JWKS on every protected route.
  Verification is centralized in `security.py`; route handlers
  receive a verified `User` from `Depends`, never a raw token.
- `user_id` is set into a `contextvars.ContextVar` at request entry
  and read by the repository for ownership checks.
- Postgres RLS is configured via `SET LOCAL app.user_id =
  '<uuid>'` at the start of every transaction and policies match
  on `current_setting('app.user_id')`.
- The client's claimed `user_id` (from a request body, query string,
  or header other than the verified Clerk JWT) is never trusted.

## Observability

- Every agent run begins with a Langfuse `trace`; every tool call is
  a `span` inside that trace.
- `mission_id` and `task_id` are propagated as trace metadata so a
  trace search by either id surfaces the full execution.
- Provider switches (primary → fallback) emit a span with
  `reason=rate_limit` or `reason=upstream_5xx`.
- Logs are structured JSON; `mission_id` and `task_id` always appear
  as top-level keys when set.

## Styling

- Use the CSS custom property tokens defined in `ui-context.md`.
  Hardcoded hex values outside the token table are a review blocker.
- Border radius follows the scale in `ui-context.md`: `rounded-sm`
  for chips, `rounded-md` for cards, `rounded-lg` for modals.
- Per-tier badge color is paired with a glyph + 2-letter code; color
  is never the sole signal (color-blind safety).
- Reasoning text renders at ~60% opacity; tool-call chips at full
  opacity but neutral fill; result previews at primary contrast.

## API Routes

- Validate and parse the request input before any logic runs.
- Verify the Clerk JWT and load `user_id` before consulting the DB.
- Apply the per-user rate limiter before consulting downstream
  services.
- Enforce ownership at the repository layer; rely on RLS as the
  backstop, not the primary check.
- Return consistent, predictable response shapes. SSE endpoints emit
  events that validate against the JSON Schema in
  `packages/sse-protocol/`.

## Data and Storage

- Mission, task, and selector metadata live in Neon Postgres.
- Parsed markdown lives in Neon (queryable via `pg_trgm`, ~10×
  smaller than HTML).
- Raw HTML snapshots live in Cloudflare R2, gzipped, 10 MB cap with
  a truncation flag.
- Never store gzipped HTML in the database; never store secrets in
  code (use env vars routed through `config.py`).
- Selector caches are owned by `persistence/repository.py` — no
  module reaches into the DB for selectors directly.
- Migrations are reviewed alongside the unit that introduces them;
  migrations that alter `missions` or `tasks` must include RLS
  policy updates in the same file.

## i18n

- All user-facing strings flow through `t(namespace, key, params?)`.
  Hardcoded English strings in components are a review blocker
  outside dev/error messages.
- Namespaces: `common`, `mission`, `validation`, `message`, `agent`,
  `task`, `discovery`, `selector`, `cost`. Add a new namespace only
  when a feature has ≥5 strings; add new keys to the existing
  namespace otherwise.
- Plurals via the `count` parameter resolve to `key_one` /
  `key_other`. The base key must exist in the type interface for
  autocomplete even though `t()` resolves to suffixed versions.
- Validators return translation keys (e.g., `'urlInvalid'`); keys
  are resolved to strings only at the UI layer.
- Test renders use `I18nTestWrapper` (flagship parity); assertions
  match the English resolution because the wrapper sets
  `initialLocale="en"`.

## File Organization

### Web (`apps/web/`)

- `app/` — Next.js routes, layouts, BFF proxy handlers
- `widgets/` — composed UI sections that own no business logic
- `features/<name>/` — user-facing business logic, owns its hooks,
  components, and i18n keys
- `entities/<name>/` — typed domain models and helpers
- `shared/` — i18n runtime, fetchers, SSE parser, command palette,
  keyboard shortcut registry
- `components/ui/` — shadcn primitives (protected; CLI-managed)

### API (`apps/api/app/`)

- `main.py` — FastAPI factory, lifecycle hooks
- `routes.py` — endpoints + DTOs
- `security.py` — JWT, SSRF, rate limit, allow-list, robots.txt
  (protected)
- `agent.py` — Pydantic AI Agent build + tool registration
- `llm/` — provider interface and adapters (OpenRouter, Groq)
- `tools/` — Scrapling tier tools + search provider
- `concurrency.py` — TaskGroup runner + semaphores
- `sse.py` — event emitter, ring buffer, `Last-Event-ID` resume
- `persistence/` — sqlmodel models, repository, blob, markdown
- `observability.py` — Langfuse init + propagation
- `jobs/` — background reaper jobs
- `config.py`, `logging.py` — env + structured logging

### Shared (`packages/sse-protocol/`)

- `schema.json` — JSON Schema (single source of truth)
- `generated/` — generated TS types and pydantic models
  (protected)
- `scripts/generate.ts` — codegen entry point
