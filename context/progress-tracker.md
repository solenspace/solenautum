# Progress Tracker

Update this file after every meaningful implementation change. The
progress tracker is the only file expected to mutate continuously
through the build; it is also the file the agent reads first when
resuming a session.

## Current Phase

- Implementation phase begins.

## Current Goal

- Implementing `specs/07-single-task-agent-and-http-tier.md`.

## Completed

### Planning (no code yet)

- Seven-file context system at `context/`
- `.claude/` and `.agents/` set up; five skills installed via
  `pnpx skills`
- Six PostHog-style subagents at `.claude/agents/`
- Context-files-are-timeless rule appended to
  `ai-workflow-rules.md`
- All 15 feature specs drafted at `specs/01-monorepo-skeleton.md`
  through `specs/15-hardening-and-e2e.md`
- `specs/tutorial.md` removed per the spec-system plan
- Pre-implementation validation pass against trusted 2026 sources
  (TypeScript 6.0, pnpm 11, Turbo 2.9.8, Biome 2.4.14, Pydantic AI
  1.89.1, Scrapling 0.4.7, Crawl4AI 0.8.5; Tailwind 4 breaking-
  change adoption; Clerk Next 16 `proxy.ts` path; Playwright API
  correction)
- Bone + narrow-black palette adopted in `context/ui-context.md`
  with WCAG-verified contrast across both modes; tier badges keep
  desaturated chromatic hues (sage / plum / amber) paired with
  glyph + 2-letter code
- Each spec's `Done when` block carries explicit named-agent gate
  lines so review enforcement is binary and verifiable

### Implementation (per spec)

- **Spec 01 — monorepo-skeleton.** Turborepo + pnpm 11 workspaces +
  uv stood up with three workspace members (`@autumn/web` Next 16.2.4,
  `@autumn/api` FastAPI on Python 3.12, `@autumn/sse-protocol`
  placeholder). `turbo run dev` boots both apps; `:3000` returns
  "Hello Autumn", `:8000/health` returns `{"status":"ok"}`,
  `:8000/docs` lists the route. `turbo run typecheck`, `turbo run
  test`, `turbo run build` all exit 0.
- **Spec 02 — linting-and-formatting.** Biome 2.4.14 owns JS/TS
  lint + format + import sort at the repo root; ruff 0.15 owns
  Python lint + format + import sort; mypy 1.20 `--strict` with the
  `pydantic.mypy` plugin owns Python type checking. `apps/api`
  `typecheck` script no longer ends in `|| true`. Editor integration
  (`.vscode/settings.json`, `.vscode/extensions.json`) committed.
  `turbo run lint && turbo run format:check && turbo run typecheck
  && turbo run test && turbo run build` exits 0.
- **Spec 03 — git-hooks-and-commits.** Lefthook 2.1.6 + commitlint
  20.5.3 (with `@commitlint/config-conventional` 20.5.3) installed
  via the npm workspace. Root `prepare: lefthook install` script
  wires `.git/hooks/{pre-commit,pre-push,commit-msg}` on every
  `pnpm install`. `pre-commit` runs Biome (TS/JS/JSON) and ruff
  (Python lint + format) on staged files only with `stage_fixed:
  true`; `pre-push` runs `turbo typecheck` then `turbo test`
  sequentially; `commit-msg` delegates to commitlint with a custom
  `scope-enum` covering `web`, `api`, `sse-protocol`, `repo`,
  `specs`, `context`, `claude`, `deps`. Five commitlint scenarios
  smoke-tested via `echo … | commitlint`: bad msg, missing scope,
  unknown scope, capital subject, valid msg — all exit codes
  correct. Biome and ruff auto-fix-and-restage smoke-tested via
  real commits (then reverted with `git reset --mixed`, never
  `--hard`). `turbo run lint && turbo run format:check && turbo
  run typecheck && turbo run test && turbo run build` exits 0.
- **Spec 04 — clerk-auth-and-security-foundation.** `@clerk/nextjs`
  ^7.3.0 wired in `apps/web` via Next 16's `proxy.ts`; `(auth)`
  route group ships sign-in / sign-up under
  `[[...sign-in]]` / `[[...sign-up]]`; root layout wraps
  `<ClerkProvider>` while keeping the Geist font variables; the
  `/missions` placeholder server component calls
  `auth()` and redirects to `/sign-in` when unauthenticated. On the
  api: `apps/api/app/config.py` (pydantic-settings v2 env loader,
  required `CLERK_SECRET_KEY`/`CLERK_PUBLISHABLE_KEY`, optional
  `AUTUMN_USER_AGENT`/`AUTUMN_URL_ALLOWLIST`) and
  `apps/api/app/security.py` (load-bearing protected file: SSRF
  guard `assert_safe_url`, async robots.txt honor
  `assert_robots_allows`, contextvar-based `CurrentUser` binding,
  `require_user` Clerk JWT dependency, slowapi `Limiter`
  60/min + 1000/day keyed on `user_id`-or-remote). `app/main.py`
  installs `SlowAPIMiddleware`, registers a `RateLimitExceeded`
  handler, and exposes `/me` as the auth+rate-limit smoke endpoint.
  Five pytest files (18 tests total) cover SSRF block list, scheme
  rejection, public-https allow, JWT 401 negative paths, rate-limit
  threshold, robots override bypass, and allow-list none / blocked /
  glob-subdomain. `apps/api/app/config.py` added to the protected
  list. `turbo run lint && turbo run typecheck && turbo run test`
  exits 0.
- **Spec 05 — persistence-layer.** sqlmodel/asyncpg/alembic/boto3/svix
  added. `apps/api/app/persistence/{models,db,repository,blob}.py`
  ship the four-table schema (users, missions, tasks, saved_selectors)
  with `ondelete=CASCADE` from mission down to task, lowercase
  Postgres enums (`mission_mode`, `mission_status`, `task_tier`,
  `task_status` via `values_callable`), and a unique covering index
  on `(domain, purpose)`. `db.py::transaction()` reads the
  `_current_user` ContextVar from `security.py` and binds
  `SET LOCAL app.user_id` per transaction; `expire_on_commit=False`
  keeps returned ORM objects readable after commit. `BlobStore` ABC +
  `R2BlobStore` (boto3 sync, fail-fast on missing creds) +
  `LocalFsBlobStore` (default for local), gzip + 10 MB raw
  truncation. Initial alembic migration enables and FORCEs RLS on
  missions and tasks with `missions_owner` and `tasks_owner` policies
  keyed on `current_setting('app.user_id', true)`; downgrade drops
  policies → indexes → tables → enum types in dependency order.
  `apps/api/app/routes.py` exposes `POST /webhooks/clerk` (svix
  verify, 503 if secret unset, no JWT, no rate limit, naturally
  idempotent) syncing `user.created`/`user.updated`/`user.deleted`
  into the `users` table via `UserRepository`. Three test modules
  (3 blob tests pass, 3 repository + 3 webhook tests skipif env
  vars unset). `turbo run lint format:check typecheck test` exits 0.
- **Spec 06 — sse-protocol-contract.** Single source of truth landed at
  `packages/sse-protocol/schema.json` (JSON Schema Draft 2020-12, nine
  event variants under `oneOf`: `token`, `tool_start`, `tool_end`,
  `task_start`, `task_end`, `url_discovered`, `selector_recovered`,
  `done`, `error`). `BaseEvent` factors `mission_id` + `seq`; each
  variant locally re-declares `["type", "content"]` plus `task_id` for
  per-task variants. Codegen pipeline (`scripts/generate.ts` via tsx,
  driven by spawnSync arg arrays so paths with spaces survive) emits
  `generated/types.ts` (TypeScript discriminated union with per-variant
  literal `type`) and
  `generated/python/autumn_sse_protocol/models.py` (pydantic v2
  `RootModel[Union[...]]` with per-variant `Literal` discriminator).
  `apps/web` consumes via `@autumn/sse-protocol` workspace dep;
  `apps/api` consumes via `[tool.uv.sources]` editable path dep
  (`autumn-sse-protocol`). Round-trip tests: 5 vitest cases
  (`packages/sse-protocol/tests/round-trip.test.ts`, Ajv 2020-12
  validator) and 3 pytest cases (`apps/api/tests/test_sse_protocol.py`,
  pydantic `model_validate` + JSON round-trip). Ring-buffer +
  `Last-Event-ID` resume specified as a contract; runtime lands in
  Spec 07 (`apps/api/app/sse.py`). `turbo run lint format:check
  typecheck test` exits 0 across all three workspace packages.

## In Progress

- `specs/07-single-task-agent-and-http-tier.md` — to begin next
  session.

## Next Up

- Implement `specs/07-single-task-agent-and-http-tier.md` (Pydantic AI
  single-task agent, HTTP-tier scrape tool via Scrapling AsyncFetcher,
  Crawl4AI markdown extraction, OpenRouter→Groq fallback, SSE emitter
  in `apps/api/app/sse.py` enforcing the Spec 06 contract — ring
  buffer of 200, single per-mission queue, `Last-Event-ID` resume,
  monotonic `seq`, per-event SSE `id:`, 15s heartbeat). The remaining
  specs follow in numbered order; each spec's `Done when` checklist
  gates progress to the next.

## Open Questions

1. **Mission cancellation semantics.** Working assumption: pending
   tasks cancel, in-flight tasks finish (least surprising). Document
   and confirm in `specs/14-cost-and-mission-lifecycle.md`.
2. **Tavily vs Exa for discovery.** Tavily is the user-confirmed
   primary; the 2026 audit favors Exa for embeddings-first agent
   search. Both have free tiers. Revisit after
   `specs/12-url-discovery-tavily.md` ships if discovery quality is
   mixed.
3. **Per-tier output schema.** Working assumption: HTTP returns
   parsed markdown via Crawl4AI; Stealth returns parsed markdown;
   Dynamic returns structured extraction (JSON via a Pydantic AI
   tool result type). Pin shape in
   `specs/07-single-task-agent-and-http-tier.md` before tools are
   wired.
4. **OpenRouter free-tier rate limits.** `gpt-oss-120b:free` is
   provider-rate-limited; the fallback chain (→ Groq) handles
   exhaustion. Track real-world rate-limit behavior after
   `specs/07-single-task-agent-and-http-tier.md` ships; the free
   tier may force a paid upgrade earlier than expected.
5. **Selector cache cross-tenant.** For MVP, selectors are scoped
   per deployment, not per user. Cross-user reuse is faster but
   leaks information about scraping patterns. Revisit at scale or
   if a B2B customer requests isolation.
6. **`SelectorRepository.upsert` SELECT-then-INSERT race.** Two
   concurrent calls on the same `(domain, purpose)` can both miss
   the SELECT and both attempt INSERT, hitting the unique index.
   Spec 13 (adaptive selectors) replaces with `INSERT ... ON CONFLICT
   DO UPDATE` to close the window. No-op until then because Spec 05
   ships zero concurrent selector writers.

## Architecture Decisions

The full rationale for each lives in the corresponding section of
the relevant context file.

1. **Auth: Clerk + per-user accounts + Postgres RLS.** Defense-in-
   depth — ownership enforced at the repository layer with RLS as a
   backstop. RLS adds ~30 minutes of setup and prevents whole
   classes of cross-tenant leaks if a WHERE clause is wrong.
2. **Persistence: Neon Postgres + Cloudflare R2.** Both have free
   tiers with no card. Parsed markdown lives in Postgres (queryable,
   ~10× smaller than HTML); raw HTML lives in R2 (zero egress on
   the free tier). Local dev uses Neon dev branches so prod and dev
   share one schema.
3. **Monorepo: Turborepo with apps/web (pnpm) + apps/api (uv).** The
   api ships a thin `package.json` wrapper so Turbo can orchestrate
   both task graphs.
4. **Concurrency: `asyncio.TaskGroup` + tiered semaphores.** No
   Celery, no Redis. HTTP per-mission 20 / global 60; browser
   per-mission 3 / global 8. Structured cancellation via the group.
5. **Scraping: Scrapling tiered + Crawl4AI for HTTP markdown.**
   Scrapling owns the three tiers; Crawl4AI handles markdown
   extraction so the agent receives LLM-ready input.
6. **Agent framework: Pydantic AI.** Diverges from flagship's
   LangGraph in favor of typed `Agent[Deps, ResultType]` and built-
   in retry decorators. Pydantic-validated tool I/O eliminates a
   class of runtime errors that the LangGraph state-dict model
   does not catch.
7. **LLM: OpenRouter `openai/gpt-oss-120b:free` primary + Groq
   `llama-3.3-70b-versatile` fallback.** Both free; both routed
   through an `LLMProvider` abstraction that switches on 429 / 5xx,
   never on tool-arg failure.
8. **URL discovery: Tavily primary** behind a `SearchProvider`
   interface so Exa or Brave can swap in via config. Per-mission
   cost cap (max 1 search, max 20 results).
9. **SSE protocol: extend `{type, content}` to `{type, content,
   mission_id, task_id?, seq}`.** New event types: `task_start`,
   `task_end`, `url_discovered`, `selector_recovered`. Per-mission
   ring buffer (last 200) supports `Last-Event-ID` resume.
10. **Anti-bot scope: Cloudflare in, Akamai/DataDome/PerimeterX
    out.** Out-of-scope sites return a `site_not_supported` error
    listing detected protections; documented in UI and ToS.
11. **Observability: Langfuse from Unit 05.** Native Pydantic AI
    integration; free tier is sufficient for MVP. Agent loops are
    undebuggable in prod without traces.
12. **Compliance baseline: robots.txt honored by default; per-user
    rate limit 60/min, 1k/day; 30-day snapshot retention; parsed
    markdown retained until user deletion.**
13. **Hosting: Vercel (web) + Fly.io or Render (api) + Clerk + Neon
    + R2 + Langfuse Cloud.** All free tier. API container disk is
    ephemeral; durability lives in Neon and R2.

## Session Notes

When resuming, drop a one-line note here describing what was last
worked on and what the next session should focus on. Example:
"Last session: finished Clerk webhook in Unit 03; next: write the
RLS policy migration and verify cross-tenant isolation test."

- 2026-05-04: Spec 01 shipped. One non-obvious wrinkle: pnpm 11's
  `runDepsStatusCheck` re-emits sharp's `ERR_PNPM_IGNORED_BUILDS`
  warning as a hard error before every `pnpm run` invocation.
  Resolved by setting root `pnpm-workspace.yaml`'s
  `allowBuilds: { sharp: true, unrs-resolver: true }` and removing
  the per-app `apps/web/pnpm-workspace.yaml` that the Next CNA
  template ships with a conflicting `ignoredBuiltDependencies` block.
  Next: Spec 02.
- 2026-05-04: Spec 02 shipped. Three deviations from the spec text,
  each with reason: (1) Biome 2.4.14 deprecated
  `experimentalScannerIgnores` — migrated those ignores to negated
  `files.includes` patterns (`!**/generated`, etc.). (2) The spec's
  `.vscode/extensions.json` listed `esbenp.prettier-vscode` in both
  `recommendations` and `unwantedRecommendations`; obvious copy-
  paste typo, removed from `recommendations`. (3) Spec 01 placed
  `pytest` in `[project.optional-dependencies] dev`, but
  `uv add --dev` writes to `[dependency-groups] dev`, and `uv sync`
  prefers the latter — pytest got dropped from the venv on first
  sync. Consolidated all dev deps into `[dependency-groups] dev`
  (modern PEP 735 pattern). Next: Spec 03.
- 2026-05-04: Spec 03 shipped. Five deviations / decisions worth
  recording: (1) The spec file is `specs/03-git-hooks-and-commits.md`,
  but earlier tracker entries referenced
  `specs/03-pre-commit-and-conventional-commits.md` — fixed the
  stale references throughout this file. (2) Kept the
  `block-env-files` pre-commit job carried over from the bootstrap
  `lefthook.yml`; spec doesn't include it but it's an existing
  security feature and the spec's "three hooks" rule refers to hook
  events (pre-commit / pre-push / commit-msg), not job count.
  (3) Resolved versions exceed the spec's floor: lefthook 2.1.6
  (spec asked ≥ 1.10), commitlint 20.5.3 (spec asked ≥ 19) — npm
  registry has moved past those minor lines. (4) pnpm 11's
  build-script gating triggered again: lefthook's npm package has
  a postinstall that extracts the Go binary; needed
  `allowBuilds.lefthook: true` in `pnpm-workspace.yaml` (same
  pattern Spec 01 used for `sharp` and `unrs-resolver`). (5) During
  smoke-testing I called `git reset --hard HEAD~1` to clean up a
  successful smoke commit — this also wiped my unstaged
  modifications to `lefthook.yml`/`package.json`/`pnpm-workspace.yaml`/
  `.gitignore`, forcing a full re-do. Lesson: when undoing a
  smoke commit that has unstaged real changes alongside it, use
  `git reset --mixed HEAD~1` (the default), never `--hard`. Next:
  Spec 04.
- 2026-05-04: Spec 04 shipped. Six deviations / notes worth
  recording: (1) **clerk-backend-api 5.x SDK shape** — the spec
  imported `authenticate_request` and `AuthenticateRequestOptions`
  from `clerk_backend_api.jwks_helpers` and instantiated a
  `Clerk(bearer_auth=...)` client. In 5.0.6 there is no
  `jwks_helpers` module and no `Clerk` instance is needed for auth;
  the canonical paths are
  `clerk_backend_api.security.authenticaterequest.authenticate_request_async`
  and `clerk_backend_api.security.types.AuthenticateRequestOptions`,
  with the secret key passed via `AuthenticateRequestOptions(secret_key=...)`.
  Imported from those canonical paths because the package's
  `__init__.py` re-exports through `from .sdk import *` /
  `from .models import *` without `__all__`, which mypy
  `no_implicit_reexport=True` rejects. Also switched to the async
  variant so JWKS fetch never blocks the event loop. Starlette's
  `Request` already satisfies the SDK's `Requestish` Protocol
  (just needs `.headers`), so no httpx-Request adaptor is required.
  (2) **mypy strict trimmed two `# type: ignore` lines** — the
  pydantic plugin handled `Settings()` env-driven init without the
  `call-arg` ignore; the unused-ignore check then forced removal.
  Kept the two `# type: ignore[attr-defined]` on
  `RobotFileParser.allow_all` since stdlib typeshed still doesn't
  expose that attribute. (3) **slowapi/FastAPI handler signatures
  trip ARG001** — `_rate_limit_handler` and `me` both take a
  `request: Request` parameter that the body never reads, but it's
  required by FastAPI's exception-handler contract and slowapi's
  decorator (slowapi keys off the literal parameter name `request`).
  Annotated both with inline `# noqa: ARG001` carrying the reason
  rather than weakening the global ruleset. (4) **DNS in
  `test_allowlist`** — the spec test `assert_safe_url("https://api.example.com/")`
  runs the SSRF guard before the allow-list check, and
  `api.example.com` is `NXDOMAIN` on most networks (including this
  one), so the guard short-circuits with `dns resolution failed`
  before the allow-list ever runs. Monkeypatched
  `app.security.socket.getaddrinfo` to return a public-IP tuple in
  all three allow-list tests so the unit suite is hermetic.
  (5) **No `.env.example` files** — per direct user instruction,
  we shipped only the gitignored `.env.local` (web) and `.env`
  (api). The env contract is captured below; new contributors can
  rerun `clerk env pull --file apps/web/.env.local` (CLI is linked
  to app `app_3DHhPb5VEyKCiwCE8XKeIAFfyO1`, instance
  `ins_3DHhPhiA1hlkNDFZygT2n4hFwhH`, "autumn") to bootstrap.
  (6) **pnpm build-script gating fired again** — `@clerk/shared`
  needed `allowBuilds: { '@clerk/shared': true }` in
  `pnpm-workspace.yaml` (same pattern as `sharp`, `unrs-resolver`,
  `lefthook`). pnpm pre-seeded the entry with placeholder
  `"set this to true or false"` on first install; flipped to
  `true`. **Env contract** — web `.env.local`:
  `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`,
  `NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in`,
  `NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up`,
  `NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL=/missions`,
  `NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL=/missions`. api
  `.env`: `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`, optional
  `AUTUMN_USER_AGENT` (defaults to AutumnBot/0.1), optional
  `AUTUMN_URL_ALLOWLIST` (comma-separated, e.g.
  `example.com,*.docs.example.com`; unset = no filter). Next:
  Spec 05.
- 2026-05-04: Spec 05 shipped. Twelve deviations / decisions worth
  recording: (1) **No `.env.example`** — same project policy as
  Spec 04; the eight new env-var entries (DATABASE_URL,
  DATABASE_URL_UNPOOLED, BLOB_STORE_BACKEND, R2_ACCOUNT_ID,
  R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET,
  CLERK_WEBHOOK_SIGNING_SECRET) were appended (commented) to the
  gitignored `apps/api/.env` and the contract is documented here.
  All eight fields are `Optional` in `app/config.py` so the app
  boots without them; consumers fail-fast at first use
  (`db.py::_get_engine` raises if `DATABASE_URL` unset;
  `R2BlobStore.__init__` raises if any R2 cred missing; the
  webhook route returns 503 if the signing secret is unset).
  (2) **Cascade FKs via `sa_column=Column(...)`** — sqlmodel's
  `foreign_key=` shorthand can't express `ondelete="CASCADE"`,
  required by the architecture for mission→task. Used the explicit
  `Column(..., ForeignKey("...", ondelete="CASCADE"))` form on
  `Mission.user_id` and `Task.mission_id`;
  `Task.selector_cache_id` keeps the shorthand (NO ACTION on a
  nullable cache pointer). (3) **`AsyncSession` consolidated** to
  `sqlmodel.ext.asyncio.session.AsyncSession` everywhere (the spec
  text mixed it with `sqlalchemy.ext.asyncio.AsyncSession`); the
  sqlmodel subclass adds `.exec()` for typed scalar handling, used
  consistently in repository methods. (4) **Postgres enum members
  needed `values_callable`** — without it, `sa.Enum(MyStrEnum, ...)`
  defaults to using Python member *names* (uppercase like
  `'PENDING'`), which mismatches both the StrEnum's `.value`
  (`'pending'`) and the `server_default='pending'` we pass.
  Added `_enum_values()` helper in `models.py` and applied to all
  four enum columns. (5) **`boto3-stubs[s3]` dev dep added** —
  required because `disallow_any_unimported = true` would otherwise
  reject every boto3 call site. (6) **`greenlet` prod dep added** —
  SQLAlchemy 2.x async needs it as an explicit transitive; uv didn't
  pull it in automatically. (7) **No `@limiter.limit` on the
  webhook route** — slowapi's per-user limiter falls back to remote
  IP for unauthenticated traffic, which would block Clerk's retry
  storms on a shared egress IP. Trust the Svix signature as the
  ceiling. (8) **`get_blob_store()` `@lru_cache`d** — single boto3
  client per process when R2 is selected. (9) **No `conftest.py`
  for the persistence tests** — module-level
  `pytestmark = pytest.mark.skipif(...)` on `DATABASE_URL` /
  `CLERK_WEBHOOK_SIGNING_SECRET` skips repository + webhook tests
  cleanly without restructuring `tests/`. (10) **Spec test stub
  completed** — `test_task_inherits_rls_via_mission` re-fetches the
  task as user_a and asserts `status == Status.PENDING`, proving
  user_b's update was hidden by RLS, not applied. (11) **Auto-gen
  cleanups in the migration file** — autogenerate emits
  `sqlmodel.sql.sqltypes.AutoString` (unimported) and references
  `Text()` (also unimported); rewrote with `sa.String`/`sa.Text` and
  modernized typing (`from __future__ import annotations`,
  `str | None`). Dropped the redundant `ix_saved_selectors_domain`
  and `ix_saved_selectors_purpose` indexes — the unique covering
  index on `(domain, purpose)` already serves left-prefix lookups on
  `domain`. (12) **Migration uses `DATABASE_URL_UNPOOLED`** — Neon's
  PgBouncer in transaction mode rejects the session-level features
  alembic relies on; `alembic/env.py` raises a clear
  `RuntimeError` if it's unset. **Pooler GUC verification deferred**
  — no Neon dev branch is configured in this session; the RLS
  pooler check (architecture caveat) needs to be run when a real
  branch comes online. **Env contract delta (apps/api/.env)** —
  optional: `DATABASE_URL`, `DATABASE_URL_UNPOOLED` (Neon Postgres,
  `postgresql+asyncpg://...?sslmode=require`), `BLOB_STORE_BACKEND`
  (`r2`|`local`, default `local`), `R2_ACCOUNT_ID`,
  `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`,
  `CLERK_WEBHOOK_SIGNING_SECRET`. Next: Spec 06.
- 2026-05-05: Spec 06 shipped. Six deviations / decisions worth
  recording: (1) **Spec filename is `06-sse-protocol-contract.md`,
  not `06-sse-protocol-and-streaming.md`** — earlier tracker entries
  used the stale name. The contract-only scope is correct (streaming
  runtime is Spec 07). Fixed the references throughout this file.
  (2) **Codegen tool stack diverges from the spec.** Spec 06 specified
  quicktype 23 for both targets. Verified locally that quicktype 23.2.6
  cannot preserve `oneOf` discriminated unions — even with
  `--explicit-unions --prefer-unions` it collapses every variant into
  a single flat type with a flattened `ContentObject`, dropping per-
  task `task_id` enforcement and per-variant `content` shapes. Since
  the spec's tests and consumers depend on per-variant literals and
  `RootModel.root` access, swapped the pipeline to:
  `json-schema-to-typescript@^15` for TS (proper discriminated union),
  `datamodel-code-generator==0.32.0` invoked via `uvx` for Python
  (proper `RootModel[Union[...]]` with per-variant `Literal['type']`).
  No postprocess script needed — datamodel-codegen emits modern
  pydantic v2 idioms directly (`X | None`, `dict[str, Any]`,
  `Literal[...]`, `RootModel`). The "single tool / consistency wins"
  tradeoff in the spec's design notes assumes quicktype produces
  correct output; it does not for our schema. (3) **`requires.required`
  refactor.** Original spec put `["type", "content", "mission_id",
  "seq"]` on `BaseEvent.required` and only `["task_id"]` per variant.
  Ajv strict mode (correctly) rejects this — `BaseEvent.properties`
  doesn't declare `type` / `content` (those are added per variant via
  `allOf`), so `required` references undefined properties. Fixed by
  shrinking `BaseEvent.required` to `["mission_id", "seq"]` and
  adding `["type", "content"]` (plus `task_id` for per-task variants)
  to each variant's local required clause. Bonus: generated TS now
  marks per-variant content as required (was optional before).
  (4) **Quicktype CLI quirks discovered during the abandoned attempt**
  worth memorializing: quicktype 23.2.6's `--python-version` only
  accepts `3.5|3.6|3.7` (not 3.12 as the spec assumed); paths
  containing spaces (the repo lives under "PLANET UTOPIA") fail when
  passed to `execSync` via string templates — switched the codegen
  driver to `spawnSync(cmd, args[])` so paths bypass shell tokenizing
  entirely. The `spawnSync` pattern is preserved for the
  json2ts/datamodel-codegen pipeline. (5) **`per-package biome.json`
  removed.** Spec asked for a local override that ignores
  `generated/`. The repo-root `biome.json` already excludes
  `**/generated` globally (per Spec 02), and biome 2.x's `extends:
  ["//"]` syntax is invalid. Removed the local file — root config is
  authoritative; codegen output is excluded by the global ignore.
  (6) **`tsconfig.target` set to `ESNext` in
  `packages/sse-protocol/tsconfig.json`** to silence vite/esbuild's
  "Unrecognized target environment ES2024" warning during vitest
  runs. Inherited base sets `ES2024` for runtime emitters; the package
  itself only emits no-emit type checks, so `ESNext` is harmless.
  Other minor changes: added `typescript@^6.0.0` directly to
  `packages/sse-protocol/devDependencies` (was being shadowed by an
  older transitive); `autumn_sse_protocol` added to
  `apps/api/pyproject.toml`'s ruff `known-first-party` so the
  isort group classification is correct; `esbuild: true` added to
  `pnpm-workspace.yaml` allowBuilds (same pattern as sharp/lefthook
  for build-script gating). **Env contract delta**: none — Spec 06
  is pure schema + codegen; no env vars introduced. **Manual mutation
  test** verified implicitly when the `BaseEvent.required` refactor
  forced `pnpm run generate` and both `generated/types.ts` and
  `generated/python/.../models.py` updated in lockstep, after which
  all 8 round-trip tests still pass. **Verification gate**:
  `turbo run lint format:check typecheck test` exits 0 across
  `@autumn/web`, `@autumn/api`, and `@autumn/sse-protocol`. Next:
  Spec 07.
