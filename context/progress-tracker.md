# Progress Tracker

Update this file after every meaningful implementation change. The
progress tracker is the only file expected to mutate continuously
through the build; it is also the file the agent reads first when
resuming a session.

## Current Phase

- Implementation phase begins.

## Current Goal

- Implementing `specs/10-taskgroup-runner.md` (TaskGroup runner +
  per-mission browser semaphore; closes Spec 08's invariant-3 deviation).

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
- **Spec 07 — single-task-agent-and-http-tier.** Pydantic AI agent
  (`Agent[HttpToolDeps, MissionResult]` with `defer_model_check=True`,
  `retries=2`, closure-captured `last_scrape: list[HttpScrapeResult]`)
  registers one tool (`scrape`) wrapping `app/tools/http.py::scrape_http`.
  HTTP-tier path: Scrapling `AsyncFetcher.get` (stealthy headers, follow
  redirects, 15s timeout) → `app/extract/__init__.py::MarkdownExtractor`
  (Crawl4AI `AsyncWebCrawler` with `AsyncHTTPCrawlerStrategy()` — no
  Playwright spawn — fed via `raw://{html}` URL scheme). LLM chain:
  `OpenRouterProvider` (`openai/gpt-oss-120b:free`) primary →
  `GroqProvider` (`llama-3.3-70b-versatile`) fallback, switching on
  HTTP 429 / 5xx only (invariant 12); both providers cap
  `ModelSettings(max_tokens=2048)`. Langfuse 2.60.10 tracing
  (`start_mission_trace` opens one trace per mission with `mission_id`
  + `task_id` + `user_id` metadata; `@observe(name="tool.scrape_http")`
  nests tool spans; `emit_provider_switch` tags the trace on fallback;
  client constructed with `enabled=False` when keys are missing).
  `app/sse.py` ships the canonical Spec 06 contract — per-mission
  `_MissionState` with monotonic `seq`, `deque(maxlen=200)` ring buffer,
  single `asyncio.Queue` (single-serialization invariant 4), 15s
  heartbeat via `asyncio.wait_for(queue.get(), timeout=15)` (no detached
  task), `Last-Event-ID` resume with replay+drain under one lock,
  synthetic `resume_lost` (no `id:` line so EventSource clients don't
  loop), terminal-event eviction with 60s grace; `setdefault` replaced
  with `.get()` so an evicted mission resurrected by reconnect emits
  `resume_lost` instead of hanging. `runner.run_url_mission` enforces
  invariants 1 / 5 / 7 / 10 / 11 / 12: `assert_safe_url` fail-fast
  before DB writes, mission + task rows persist before the first SSE
  event, success and failure paths share one `try/except` so a transient
  DB error in the post-agent block still emits terminal `error` + `done`,
  `_emit` helper centralizes the `seq=0`-placeholder convention, SSE
  status fields use the protocol's `Status` / `MissionStatus` / `Tier`
  enums (not raw strings or persistence-layer enums). `/run-mission`
  GET endpoint (`@limiter.limit("60/minute")`, `Last-Event-ID` header
  threaded into `emitter.stream`) awaits the runner inline — Spec 10
  separates start from streaming. FastAPI `lifespan` calls
  `probe_providers()` at boot, logging credential presence per provider
  + Langfuse without firing any token-spending completion. Five new
  `Settings` fields added (`OPENROUTER_API_KEY`, `GROQ_API_KEY`,
  `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`), all
  Optional with defaults so the api boots without keys; `apps/api/.env`
  carries commented entries. Four test files (`test_llm_chain.py` —
  five cases proving invariant 12 (no fallback on 400 / non-HTTP
  exceptions); `test_sse_emitter.py` — four cases including the
  boundary case `last_event_id == oldest_seq - 1`; `test_http_tool.py`
  — five SSRF parameterized cases; `test_run_mission_route.py` — two
  end-to-end cases gated on `DATABASE_URL`, stubbing the agent + tool
  to exercise the SSE pipeline + DB persistence hermetically). Five
  named-agent gates ran (scrape-pipeline-doctor, prompt-engineer,
  sse-streaming-reviewer, llm-cost-guard, code-reviewer); each issue
  surfaced was fixed before merge. `simplify` skill pass collapsed five
  `SseEvent.model_validate(...)` blocks into the `_emit` helper, threaded
  the protocol enums through, and removed the no-op `errors="replace"`
  on `str.encode("utf-8")` in the extractor. `turbo run lint
  format:check typecheck test build` exits 0 (41 passed, 8 skipped —
  the skips are the `DATABASE_URL`-gated tests).

- **Spec 08 — web-shell-and-stream-consumer.** Tailwind 4 + shadcn 4
  (`base-nova` style, `--base radix` initially requested but the latest
  CLI ships with `@base-ui/react` primitives — accepted; Base UI Dialog
  is API-compatible with the spec's Radix-based code) initialized in
  `apps/web/` with `pnpm dlx shadcn@latest init -d -y --no-monorepo`;
  ten primitives added (`button`, `input`, `dialog`, `sheet`, `command`,
  `kbd`, `separator`, `scroll-area`, `sidebar`, `tooltip` — plus
  `textarea`, `skeleton`, `input-group` pulled in as transitive deps).
  `lib/utils.ts` moved to `shared/utils/cn.ts` and `components.json`
  aliases rewired (`utils → @/shared/utils/cn`, `hooks → @/shared/hooks`,
  `lib → @/shared/utils`). `globals.css` rewritten with Tailwind 4
  syntax (`@import "tailwindcss"`, `@theme inline`, `--radius: 0.375rem`)
  bridging shadcn variables to the bone+narrow-black palette from
  `ui-context.md` for both light and dark modes (full color token table
  including sidebar, accent, state-success, state-error). i18n primitive
  bootstrapped at `shared/i18n/`: typed `EN` table for `common`,
  `mission`, `validation` namespaces (24+ keys); pure `translate()` with
  `{name}` interpolation + plural `_one`/`_other` lookup; `I18nProvider`
  + `useT` (single-locale today, locale-extensible signature);
  `I18nTestWrapper` for Vitest. Keyboard registry at `shared/keyboard/`
  with `useShortcut(combo, handler, options?)` supporting normalized
  `⌘`/`cmd`/`ctrl`/`⇧`/`shift` parsing, optional `allowInInput` opt-in
  (top-bar URL field uses it for `Cmd+Enter`), and the `KeyboardShortcuts`
  shell-level mount placeholder. FSD layout: `entities/mission/types.ts`
  (`MissionRow`, `MissionStatus`, `MissionMode`); `features/run-mission/`
  ships `store.ts` (zustand `openMissionId`), `use-submit-mission.ts`
  (zod URL schema, validators return keys not strings, exported
  `SubmitMissionError` literal union), `use-missions.ts` (5s polling
  with `visibilitychange` pause, grouped `byStatus`), `use-recent-
  missions.ts` (last-3 terminals), `use-mission-stream.ts` (single
  `EventSource`, `localStorage` seq tracking, `?after=<seq>` resume,
  unbounded events array — flagged for Spec 11 cap), `index.ts`
  re-exports. Widgets: `top-bar` (44px h-11 with brand wordmark,
  persistent URL input, `/` focus + `Cmd+Enter` submit), `mission-
  sidebar` + `mission-row` (32px rows, status dot + 8-char id +
  truncated URL + relative time), `mission-detail` (slide-over Sheet
  accepting `renderBody` callback; FSD-clean — no sibling cross-import),
  `task-lane-card` + `tier-badge`/`tool-chip`/`reasoning-stream`/
  `result-preview` (3-tier hierarchy: dim reasoning → neutral chips →
  high-contrast result), `command-palette` (cmdk via shadcn Command;
  Cmd+K toggle; sections: Recent / Actions / Account). App shell:
  `app/(app)/layout.tsx` (server component, `await auth()` redirect)
  composes top bar + sidebar + main + palette + KeyboardShortcuts
  inside `SidebarProvider`; `app/(app)/missions/page.tsx` renders
  `EmptyState` + `MissionDetailSlideover` with `<TaskLaneCard>`
  composed at the page layer; old `app/missions/page.tsx` placeholder
  deleted. BFF routes (`runtime = "nodejs"`): `app/api/missions/route.ts`
  (POST + GET with Clerk JWT forwarding), `app/api/missions/[id]/
  route.ts` (single-mission JSON), `app/api/missions/[id]/stream/
  route.ts` (SSE proxy: prefers browser-set `Last-Event-ID` header on
  auto-reconnect over the mount-time `?after=<seq>` query param;
  forwards `request.signal` so client disconnects propagate to the api
  immediately instead of waiting for the 60s eviction grace; passes
  `upstream.body` `ReadableStream` through verbatim — no buffering).
  `RouteContext<'/api/missions/[id]/stream'>` typing + `await
  ctx.params` per Next 16 conventions; `next typegen` runs cleanly.
  API side: `runner.py` split into `_create_mission_and_task` (SSRF +
  rows + `task_start` emission), `_execute_url_mission` (agent loop +
  terminal events; defensive contextvar re-bind), `_spawn_detached`
  (module-level `_inflight_tasks` set + `add_done_callback(discard)`
  carrying `# TODO(spec-10): TaskGroup ownership` marker — explicit
  invariant-3 deviation accepted), `start_url_mission` (returns mission
  id immediately), `run_url_mission` (compatibility shim that awaits
  inline so the legacy `GET /run-mission?url=...` test stays green).
  `routes.py`: `POST /missions` (returns `{mission_id}` 201), `GET
  /missions` (list_all, JSON), `GET /missions/{id}` (single, 404 on
  cross-tenant), `GET /run-mission/{id}/stream` (ownership lookup
  fast-path 404 + `emitter.stream(...)` with `Last-Event-ID` header);
  shared `_stream_response` helper between legacy and new endpoints.
  `MissionRepository.list_all()` added (newest-first, RLS + explicit
  `user_id` filter). Three new pytest cases (POST mission quick-return,
  stream replay terminal, list_all RLS isolation; all DB-gated). Three
  Vitest test files: `translate` (4 cases), `useShortcut` (6 cases),
  `useMissionStream` (6 cases with FakeEventSource), `useSubmitMission`
  (5 cases with mock fetch). 21 web tests + existing api tests pass.
  `vitest.config.mts` + `vitest.setup.mts` (jsdom `localStorage`
  polyfill because jsdom 29 ships an opaque proxy; Storage Map-backed
  shim covers `getItem`/`setItem`/`clear`/`key`/`length`/`removeItem`).
  `@vitejs/plugin-react@4` paired with `vitest@^3` for Vite 5 peer
  alignment. Repo-root `biome.json` extends ignore list to
  `apps/web/components/ui/**` and `apps/web/shared/hooks/use-mobile.ts`
  (shadcn-generated, protected). `pnpm-workspace.yaml` adds `msw: true`
  to `allowBuilds` (shadcn dlx pulls msw transitively). Three named-
  agent gates ran (`fsd-architect`: caught a sibling cross-import of
  TaskLaneCard from MissionDetailSlideover — fixed by lifting
  composition to `app/(app)/missions/page.tsx` via `renderBody` prop;
  `i18n-keeper`: caught `EN[namespace] as Record<string,string>` cast
  needing `unknown` intermediate, hardcoded `Autumn` brand wordmark
  needing `common.brandName` key, malformed `noMissionsHint` template
  needing `noMissionsHintPrefix` companion key, `error as <union>` cast
  in top-bar needing exported `SubmitMissionError` literal union;
  `sse-streaming-reviewer`: caught BFF stream proxy missing
  `request.signal` propagation and missing browser-set `Last-Event-ID`
  preference). All four classes of finding fixed in the diff before
  merge. `turbo run lint format:check typecheck test build` exits 0.
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
- **Spec 09 — stealth-and-dynamic-tier-tools.** Multi-tier scrape
  pipeline shipped with three Pydantic AI tools (`scrape_http`,
  `scrape_stealth`, `scrape_dynamic`) registered against
  `Agent[MissionDeps, MissionResult]`. Each returns a typed
  discriminated union (`*ScrapeOk | *ScrapeFailure`); the agent's
  system prompt drives escalation
  (`protected_cloudflare`→stealth, `javascript_required`→dynamic,
  `site_not_supported`/`not_found`/`upstream_error`/`render_timeout`
  →terminal). New `apps/api/app/tools/_waf.py` ships pure WAF
  fingerprint classifier (`detect_waf` + `body_excerpt` + `TERMINAL_WAFS`
  frozenset) covering CF (server / cf-ray / body), Akamai
  (AkamaiGHost / x-akamai / `ak-*`), DataDome (x-datadome / set-cookie
  fingerprint), PerimeterX (x-iinfo / `_pxhd` / `px-captcha`). New
  `apps/api/app/concurrency.py` ships `_GLOBAL_HTTP =
  asyncio.Semaphore(60)` and `_GLOBAL_BROWSER = asyncio.Semaphore(8)`
  with `http_slot()` / `browser_slot()` `@asynccontextmanager`
  helpers; both browser-tier tools acquire `browser_slot()` around
  `StealthyFetcher.async_fetch` / `PlayWrightFetcher.async_fetch`
  invocations (invariant 2). `http_slot` defined but not yet wired
  (Spec 10 wires it). New `apps/api/app/persistence/snapshot.py`
  exposes `persist_snapshot(*, user_id, mission_id, task_id, raw_html,
  store=None)` as the single chokepoint to `BlobStore.put` (invariant 9
  write-once); all three tier tools route through it on success,
  closing Spec 07's snapshot stub (`tasks.snapshot_key` and
  `tasks.snapshot_truncated` now populated). New
  `apps/api/app/runner_helpers.py::_last_ok_tool_call(result)` walks
  Pydantic AI's `result.all_messages()` in reverse, returning the
  most recent `ToolReturnPart` whose content is a `*Ok` model;
  defensive dict-form fallback handles future patch-version
  serialization shifts. `MissionResult` extended with
  `status: Literal["ok", "error"]`, `error_code:
  Literal["site_not_supported", "upstream_error", "not_found",
  "render_timeout", "agent_failed"] | None`, and
  `detected_protections: list[str]`. The runner reads
  `mission_result.status`, emits an SSE `error` event with the typed
  `code` BEFORE the terminal `task_end`/`done`, and writes
  `tasks.parsed_markdown`/`snapshot_key`/`latency_ms` from the
  recovered tool call. The legacy `last_scrape: list[]` closure
  pattern is gone. Web side adds four `mission.error*` i18n keys
  (`errorSiteNotSupported` with `{protections}` interpolation,
  `errorNotFound`, `errorRenderTimeout`, `errorUpstream`); the new
  `<ErrorChip>` inside `widgets/task-lane-card/result-preview.tsx`
  renders inline above the preview block, keyed off the SSE `code`
  via a `_ERROR_KEYS` lookup table; falls back to
  `error.content.message` for unrecognized codes. `_project()` in
  `widgets/task-lane-card/index.tsx` extends to capture `error`
  events alongside `tool_start`/`tool_end`/`task_end`. Six new
  pytest files (`test_waf.py` 8 cases / `test_concurrency.py` 2
  cases including a saturation test that asserts `peak <= 8` via an
  in-flight counter / `test_snapshot_helper.py` round-trip with
  `LocalFsBlobStore` / `test_stealth_tool.py` + `test_dynamic_tool.py`
  5 SSRF cases each / `test_runner_error_propagation.py` 2 cases
  end-to-end with mocked LLM and Akamai-fixture HTTP);
  `test_http_tool.py` updated for the new `BaseModel HttpToolDeps`
  signature plus a 6th case proving 403+CF returns
  `HttpScrapeFailure(reason="protected_cloudflare")` (no raise);
  `test_run_mission_route.py` rewritten to drive the new
  `MissionResult(status="ok", ...)` shape and walk the agent's
  `all_messages()` via a real `ToolReturnPart` carrying an
  `HttpScrapeOk`. New web Vitest spec
  `widgets/task-lane-card/result-preview.test.tsx` (9 cases) covers
  empty render, taskEnd preview, all four typed error codes
  (with `{protections}` interpolation), the unrecognized-code
  fallback, and combined chip+preview rendering. **Six explicit
  spec deviations** (all greenlit with rationale): (1) Scrapling
  0.2.99 `StealthyFetcher.async_fetch` / `PlayWrightFetcher.async_fetch`
  used instead of the spec's `AsyncStealthySession` /
  `AsyncDynamicSession` — Scrapling 0.3+ requires `lxml>=6.0.2`
  which conflicts with `crawl4ai==0.8.6`'s `lxml~=5.3` pin
  (open question: bump crawl4ai or replace it in a later spec);
  Response shape (`.status`/`.headers`/`.body`/`.url`) is
  identical so all WAF-routing logic is preserved; lost only the
  `solve_cloudflare=True` kwarg — CF-JS-challenge variants surface
  as `javascript_required` and escalate to dynamic, which is the
  spec's intended fallback anyway. (2) `build_agent()` keeps Spec
  07's `defer_model_check=True` pattern (model passed via
  `agent.run(model=, deps=...)`) instead of the spec's
  `build_agent(model_factory)` — equivalent semantics, avoids
  re-allocating the agent on each LLM-fallback attempt; documented
  in the agent.py docstring. (3) Web error chip rendered inside
  `<ResultPreview>` via `errors?: SseError[]` prop — no new file
  in `widgets/task-lane-card/`. (4) SSE schema not edited — the
  `code` field is already a free `string` per
  `packages/sse-protocol/schema.json:198-202`; new codes are valid
  string values today (the schema description even lists
  `site_not_supported` as an example). (5) `http_slot()` defined
  but NOT wired into `scrape_http` — Spec 10 wires it with the
  TaskGroup runner. (6) `task.tier_used` not updated after
  agent escalation — initial `Tier.HTTP` assignment stays;
  rewriting after escalation is a future-spec concern (commented
  inline). **Four named-agent gates** ran on the chunk and all
  returned PASS / Approve: `scrape-pipeline-doctor` confirmed
  invariants 1, 2, 3, 5, 6, 7, 9, 10, 11, 12 hold; `prompt-engineer`
  confirmed three-tool registration + system-prompt verbatim per
  Spec 09 lines 510-532; `llm-cost-guard` confirmed bounded retries
  (`retries=2`), `max_tokens=2048` on both providers, no new
  routes, no tool re-prompts the LLM with full markdown
  (a soft concern flagged: no outer mission-level deadline guard
  on `chain.with_fallback(_run)` — worst case ~90s on a
  dynamic-tier retry storm; tracked for follow-up); `code-reviewer`
  produced `Verdict: Approve` (`CODE_REVIEW.md` consumed and
  deleted per project policy). `simplify` skill pass extracted
  `_body_excerpt` and `TERMINAL_WAFS` to `app/tools/_waf.py`
  (eliminating triplicated helpers across the three tier tools),
  hoisted `MarkdownExtractor()` to module-level singletons,
  flattened the `<ErrorChip>` if/else chain to a `_ERROR_KEYS`
  lookup table, dropped the redundant
  `Record<string, unknown>` cast in `result-preview.tsx`,
  switched from `Extract<SseEvent, {type:"error"}>` to direct
  `SseError` import, bound `final_status`/`sse_status_value`/
  `mission_status_value` once in the runner, trimmed the
  verbose module docstrings in the tier tools, and tightened
  `test_browser_slot_serializes_at_capacity` to assert
  `peak <= 8` (the original count-based assertion would have
  passed at any concurrency level). **Verification gate**:
  `pnpm exec turbo run lint format:check typecheck test build`
  exits 0; pytest reports 63 passed, 14 skipped (the 14 are
  `DATABASE_URL`-gated, same pattern as Specs 05/07/08); web
  Vitest reports 30 passed (5 test files including the new
  `result-preview.test.tsx`).

## In Progress

- `specs/10-taskgroup-runner.md` — to begin next session. Closes
  Spec 08's invariant-3 deviation (`_spawn_detached` →
  `TaskGroup.create_task`) and adds per-mission HTTP/browser
  semaphores (HTTP 20, browser 3) on top of Spec 09's global
  ceilings.

## Next Up

- Implement `specs/10-taskgroup-runner.md`. The remaining specs
  follow in numbered order; each spec's `Done when` checklist
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
3. **Per-tier output schema.** **HTTP-tier resolved in Spec 07**:
   `HttpScrapeResult` Pydantic model — `url: str`, `markdown: str`
   (Crawl4AI `DefaultMarkdownGenerator` via `AsyncHTTPCrawlerStrategy`),
   `raw_html: bytes`, `latency_ms: int`. The agent's typed output is
   `MissionResult` (`summary`, `primary_url`, `markdown_excerpt`); the
   runner persists the full markdown via the closure-captured tool
   result. Stealth + Dynamic tiers (Specs 09, 13) will return
   `HttpScrapeResult`-shaped models for parsed-markdown paths and a
   structured `Extracted[T]` model for JSON extraction.
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
7. **Spec 10 must close `runner._spawn_detached` invariant-3
   deviation.** `apps/api/app/runner.py::_spawn_detached` uses
   `asyncio.create_task` outside a TaskGroup with a `# TODO(spec-10)`
   marker. The detached task is held alive by `_inflight_tasks` set
   + `add_done_callback(discard)` to avoid GC, but ownership is not
   structured. Spec 10 replaces with `TaskGroup.create_task` and
   call sites stay unchanged. The `scrape-pipeline-doctor` review of
   Spec 10 fails until this lands.
8. **Spec 08 verification deferred to human reviewer.** Two
   verification items in `specs/08-web-shell-and-stream-consumer.md`
   require a real Clerk dev instance + browser run and are not
   agent-executable: (a) Lighthouse / axe accessibility pass on
   `/missions`, (b) live 10-second mission against
   `https://example.com/` rendering the three-tier slide-over end
   to end, plus the manual real-network reconnect test (kill network
   mid-stream → `state.reconnecting` flips and recovers). All
   code-level gates (`turbo run lint format:check typecheck test
   build`, `fsd-architect`, `i18n-keeper`, `sse-streaming-reviewer`,
   `simplify`) pass.
9. **Spec 08 SSE multi-consumer caveat (deferred to Spec 11).** A
   single per-mission queue means a tab reload that opens a second
   `emitter.stream(mission_id, ...)` while the first is still draining
   will steal events from the first via the `get_nowait()` drain in
   `apps/api/app/sse.py`. Spec 08 ships single-consumer-per-tab in
   practice; Spec 11's multi-lane stack revisits with a fan-out queue
   if the reload race becomes user-visible.
10. **Spec 08 client-side events array unbounded (deferred to Spec
    11).** `use-mission-stream.ts` appends to `events` without a cap;
    a long mission (>1000 tokens) eventually scales O(n) on each
    append. Spec 11 multi-lane case will need a per-lane cap (e.g.
    last 1000) plus a `truncated_count` for the older-events
    indicator.
11. **Spec 09 Scrapling/lxml dep-tree conflict.** `crawl4ai==0.8.6`
    pins `lxml~=5.3` while `scrapling>=0.3` requires `lxml>=6.0.2`.
    Today's pin is `scrapling==0.2.99` which exposes
    `StealthyFetcher.async_fetch` / `PlayWrightFetcher.async_fetch`
    rather than the spec's `AsyncStealthySession` /
    `AsyncDynamicSession` async-context-manager API. Behavior
    parity: Response shape is identical, semaphore wraps the call
    correctly, all 12 invariants hold. Lost: the
    `solve_cloudflare=True` kwarg — CF-JS-challenge variants are
    routed to `javascript_required` and escalate to the dynamic
    tier (the spec's intended fallback anyway). Resolution path:
    bump `crawl4ai` to a release that supports `lxml>=6` (none
    exists as of 2026-05-06; latest is 0.8.6) OR replace
    `MarkdownExtractor` with a lxml-6-compatible alternative
    (markdownify + readability). Defer to Spec 12 (URL discovery)
    or whichever spec next touches the markdown pipeline.
12. **Spec 09 mission-level deadline guard (open).** `llm-cost-guard`
    flagged a soft concern: `chain.with_fallback(_run)` in
    `runner.py:154` has no outer `asyncio.timeout(...)` wrapper.
    Worst case on a dynamic-tier retry storm is ~90s
    (3 × 30s Playwright timeouts) before the runner emits
    `render_timeout`. Not a credit-drain risk (Playwright timeouts
    never reach the LLM) but holds a `browser_slot` and an open
    SSE connection past 30s. Spec 14 (cost-and-mission-lifecycle)
    is the natural home; track until then.
13. **Spec 09 `task.tier_used` not updated after escalation.**
    Initial assignment of `Tier.HTTP` at task creation stays even
    when the agent escalates to stealth or dynamic. The tier badge
    in the UI reads from the SSE `task_start` event, also stuck on
    `http`. Future-spec concern (Spec 11 multi-lane stack will
    likely surface per-tier status anyway). Inline TODO at
    `runner.py:96`.
14. **Spec 09 `architecture.md` doc drift.** The Stack table at
    `context/architecture.md:20` references
    `AsyncStealthySession(solve_cloudflare=True)`; reality (per
    Open Question 11 above) is `StealthyFetcher.async_fetch`.
    Update the Stack table when bumping Scrapling/crawl4ai or
    replacing the markdown pipeline.
15. **Spec 09 `_coerce_ok` dict fallback is dead code today.**
    `runner_helpers.py::_coerce_ok` accepts both Pydantic-model and
    dict shapes for `ToolReturnPart.content`. Pydantic AI 1.44.0
    always passes the model instance, so the dict path is
    untested. Kept defensively against patch-version
    serialization shifts; consider removing if a future Pydantic
    AI minor cuts the model-instance contract from its public API.

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
- 2026-05-05: Spec 07 shipped. Eleven deviations / decisions worth
  recording: (1) **Library versions diverge from the planning audit.**
  Tracker's pre-implementation notes called for Pydantic AI 1.89.1 /
  Scrapling 0.4.7 / Crawl4AI 0.8.5; uv resolved `pydantic-ai==1.44.0`,
  `langfuse==2.60.10`, `scrapling==0.2.99`, `crawl4ai==0.8.6`. Scrapling
  >= 0.3 conflicts with Crawl4AI's `lxml<6` constraint, so 0.2.99 is
  the highest compatible release. Pydantic AI defaulted to 0.0.30 from
  a stale lower bound; tightened the `pyproject.toml` constraint to
  `>=0.5` to pull 1.44. (2) **Crawl4AI `raw://` API differs from the
  spec's draft.** The spec's `MarkdownExtractor` passed `html=` as a
  kwarg to `arun(...)`; in 0.8.6 that's silently ignored — the HTML
  must be embedded in the URL itself (`url=f"raw://{html}"`). Also
  swapped `BrowserConfig` for `AsyncHTTPCrawlerStrategy()` so no
  Playwright session is spawned for already-fetched HTML. (3)
  **Scrapling `AsyncFetcher.get` is a classmethod**, not an instance
  method (the spec's draft instantiated `AsyncFetcher()` first). Calling
  `AsyncFetcher.get(url, ...)` directly avoids a deprecation warning
  the package logs at instantiation. (4) **`scrapling.Response.body`
  is a `TextHandler` (subclass of `str`), not bytes** — the spec's
  pipeline assumed bytes. `MarkdownExtractor.extract(html: str)` now
  takes a decoded string; `ExtractedPage.raw_html` re-encodes via
  `str.encode("utf-8")` (lossless because Python `str` is unicode).
  (5) **`MissionRepository.create()` does not take `user_id=`**; the
  spec's draft did. The actual repo (Spec 05) reads `user_id` from
  `_current_user`. The runner sets the contextvar via
  `_current_user.set(user)` and the SET LOCAL flows through `transaction()`
  into RLS. (6) **Closure-captured `last_scrape: list[HttpScrapeResult]`
  inside `build_agent()`** lets the runner persist the *full* parsed
  markdown (not just the 500-char `MissionResult.markdown_excerpt`).
  `_run` calls `last_scrape.clear()` at every chain attempt so a
  primary→fallback transition can't merge two tool histories. (7)
  **Mypy strict needs `[[tool.mypy.overrides]]` blocks** for the four
  new untyped deps (`crawl4ai.*`, `langfuse.*`, `scrapling.*`,
  `autumn_sse_protocol.*`) plus a handful of per-line `# type: ignore`
  comments — `[no-any-unimported]` on the `SseEvent`/`Langfuse`/
  `StatefulTraceClient` annotations, `[untyped-decorator]` on the
  `@observe(...)` over `scrape_http`. (8) **Five env-var fields are
  Optional** (`OPENROUTER_API_KEY`, `GROQ_API_KEY`,
  `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`) so
  CI / fresh checkouts boot without keys; `Langfuse(enabled=False)` is
  the no-op posture when keys are missing, and `LLMProviderChain`
  raises at first call rather than at construction. (9) **The startup
  `probe_providers()` is intentionally credentials-only** — it does
  not fire a real completion. The spec's draft asked for a 1-token
  completion at boot; on free-tier rate limits that would burn the
  window. Probe just logs `configured` / `missing` per provider; real
  availability surfaces on the first mission. (10) **R2 snapshot upload
  is intentionally NOT wired** per the spec's "Out of Scope" block —
  `tasks.snapshot_key=None`, `tasks.snapshot_truncated=False`. Spec
  09/10 introduces the uniform tier-result handling. (11) **Five named-
  agent gates ran and surfaced four real fixes that landed in the
  diff**: (a) `runner.run_url_mission` success path was outside the
  `try/except`, so a transient DB error mid-success would leave the
  task without a terminal event — wrapped in the same try/except as
  the failure terminals (invariant 5). (b) `start_mission_trace`
  signature gained `task_id: UUID` so trace metadata carries both ids
  per `code-standards.md`. (c) `SseEmitter.stream` switched
  `setdefault` → `.get()` so an evicted-then-resurrected mission emits
  `resume_lost` instead of hanging on an empty queue. (d) `simplify`
  pass added an `_emit` helper, threaded the protocol's `Status` /
  `MissionStatus` / `Tier` enums into the SSE content fields, and
  removed the no-op `errors="replace"` on `str.encode("utf-8")` in the
  extractor. **Env contract delta (apps/api/.env)** — optional:
  `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `LANGFUSE_PUBLIC_KEY`,
  `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` (default
  `https://cloud.langfuse.com`). **Verification gate**: `pnpm exec
  turbo run lint format:check typecheck test build` exits 0; pytest
  reports 41 passed, 8 skipped (all 8 are `DATABASE_URL`-gated, same
  pattern as Spec 05). Next: Spec 08.
- 2026-05-05: Spec 08 shipped. Twelve deviations / decisions worth
  recording: (1) **Spec filename and tracker name out of sync.**
  Tracker referenced `specs/08-mission-form-and-stream-ui.md` but the
  actual spec file is `specs/08-web-shell-and-stream-consumer.md`.
  Updated tracker references throughout. (2) **shadcn 4 / Base UI
  primitives, not Radix.** Spec assumed older shadcn (`new-york`
  style + Radix); the current CLI ships `base-nova` + `@base-ui/react`
  primitives. Base UI's `Dialog`/`Popover` are API-compatible with
  the spec's `open`/`onOpenChange` patterns, so widgets render
  identically. `--style="new-york"` flag is no longer accepted; used
  `npx shadcn@latest init -d -y --no-monorepo` (defaults: next
  template, base-nova preset). (3) **`pnpm dlx shadcn` exited nonzero
  on `ERR_PNPM_IGNORED_BUILDS msw@2.14.3`** — added `msw: true` to
  `pnpm-workspace.yaml` `allowBuilds` and switched to `npx`.
  Pattern continues for build-script gating (`sharp`, `unrs-resolver`,
  `lefthook`, `@clerk/shared`, `esbuild` already present).
  (4) **shadcn aliases moved.** CLI generated `lib/utils.ts`; moved
  to `shared/utils/cn.ts` and rewrote `components.json` aliases:
  `utils → @/shared/utils/cn`, `lib → @/shared/utils`,
  `hooks → @/shared/hooks`. The CLI's `--add` ran cleanly against the
  rewired aliases (verified via `shared/hooks/use-mobile.ts`). (5)
  **Tailwind 4 globals.css.** CLI initial output uses `oklch()` and
  ships chart/sidebar tokens. Replaced with hex values from
  `context/ui-context.md` bone+narrow-black palette for both modes
  (`--background`, `--foreground`, `--primary`, `--ring`,
  `--destructive`, `--card`, `--popover`, `--accent`, `--muted`,
  `--state-success`, `--state-error`, full sidebar quartet) plus
  `--radius: 0.375rem`. Imports kept: `@import "tailwindcss"`,
  `@import "tw-animate-css"`, `@import "shadcn/tailwind.css"`,
  `@custom-variant dark (&:is(.dark *))`, `@theme inline { ... }`,
  `@layer base`. (6) **Vitest 3 + plugin-react 4 alignment.**
  `@vitejs/plugin-react@6` is ESM-only and requires Vite 6 peers;
  Vitest 2 ships Vite 5. Pinned to `vitest@^3` + `@vitejs/plugin-
  react@4`. Renamed `vitest.config.ts` → `vitest.config.mts` (ESM
  loader) and same for setup. `cssVariables: true` `outline-hidden`
  Tailwind 4 classes work via shadcn's variants. (7) **jsdom 29
  localStorage shim.** `vitest.setup.mts` polyfills a Map-backed
  `Storage` over `window.localStorage` because jsdom 29 ships an
  opaque proxy where `getItem`/`setItem`/`clear` are not real
  methods. Without the shim, `useMissionStream`'s try/catch swallows
  silently in production but tests fail loudly. (8) **i18n primitive
  bootstrapped this spec.** Spec assumed it existed; codebase had
  nothing under `apps/web/shared/i18n/`. Built the minimum that
  satisfies `code-standards.md`: typed `EN` table for `common`,
  `mission`, `validation` with all 24+ keys; pure
  `translate(namespace, key, params?)` with `{name}` interpolation +
  plural lookup; `I18nProvider` + `useT` (single English locale
  today, signature stable for future locales); `I18nTestWrapper`
  for Vitest. (9) **Runner refactor preserves the existing
  `/run-mission?url=...` route test.** Split `run_url_mission` into
  `_create_mission_and_task` + `_execute_url_mission` +
  `_spawn_detached`; kept `run_url_mission` as a thin shim that
  awaits both inline so the legacy test still reads the full
  terminal SSE sequence in one shot. The new `start_url_mission`
  fires `_execute_url_mission` via `_spawn_detached` and returns
  immediately. `_inflight_tasks` set + `add_done_callback(discard)`
  prevents GC mid-flight; `# TODO(spec-10)` marker carries the
  invariant-3 deviation accepted by the spec. (10) **BFF stream
  proxy `request.signal` + browser `Last-Event-ID` priority.**
  `sse-streaming-reviewer` flagged two corrections to the initial
  draft: (a) `fetch(...)` upstream needs `signal: request.signal`
  so client disconnects propagate immediately to the api instead of
  waiting for the 60s eviction grace; (b) on EventSource auto-
  reconnect the browser sends a real `Last-Event-ID` header — the
  BFF prefers it over the (now-stale) mount-time `?after=<seq>`
  query param. Both landed before merge. (11) **FSD sibling
  cross-import lifted.** `fsd-architect` flagged
  `widgets/mission-detail/index.tsx` importing `TaskLaneCard` from
  `widgets/task-lane-card`. Refactored `MissionDetailSlideover` to
  accept a `renderBody: (missionId) => ReactNode` prop;
  `app/(app)/missions/page.tsx` composes
  `<TaskLaneCard missionId={...} />` so the slide-over no longer
  sees a sibling widget. (12) **i18n-keeper findings collapsed**:
  hardcoded `Autumn` brand → `t("common", "brandName")`;
  `error as <union>` cast → exported `SubmitMissionError` literal
  union from the hook; `EN[namespace] as Record<string, string>` →
  `as unknown as Record<string, string>` per the user-memory
  TypeScript gotcha. **simplify skill triple landed**: BFF dedupe to
  `shared/bff/upstream.ts`, `useMemo` for sidebar grouping, single-
  pass projection in `task-lane-card/index.tsx`, repository
  singletons in `runner.py`. **Env contract delta (apps/web/.env.local)**
  — optional: `AUTUMN_API_URL` (default `http://localhost:8000`),
  used by all three BFF route files via `shared/bff/upstream.ts`.
  **Verification gate**: `pnpm exec turbo run lint format:check
  typecheck test build` exits 0 (14/14 tasks, 4 cached); 21 web
  Vitest cases pass (translate / useShortcut / useMissionStream /
  useSubmitMission); api pytest 41 passed, 12 skipped (the 4 new
  cases — POST mission quick-return, stream replay, ownership 404,
  list_all RLS — are `DATABASE_URL`-gated, same pattern as Spec 05/
  07). Two Done-when items are deferred to a human reviewer (live
  Clerk smoke + Lighthouse/axe), logged in Open Questions #8.
  Next: Spec 09.
- 2026-05-06: Spec 09 shipped on
  `feature/spec-09-stealth-and-dynamic-tier-tools`. Key wrinkle was
  the Scrapling/lxml dep-tree conflict (Open Question 11): pinned
  `scrapling==0.2.99` does NOT export `AsyncStealthySession` /
  `AsyncDynamicSession` (those land in 0.3+, which requires
  `lxml>=6.0.2`, conflicting with `crawl4ai==0.8.6`'s `lxml~=5.3`).
  Pivoted to `StealthyFetcher.async_fetch(...)` /
  `PlayWrightFetcher.async_fetch(...)` — same Response shape
  (`.status`/`.headers`/`.body`/`.url`), all WAF-routing and
  invariant-2 semaphore wrapping preserved. The simplify pass
  found three identical `_body_excerpt` helpers across the tier
  tools and an `{"akamai", "datadome", "perimeterx"}` set
  literal repeated three times — both extracted to `_waf.py` as
  `body_excerpt(body, limit=4096)` and `TERMINAL_WAFS:
  frozenset[WafKind]`. The ResultPreview ErrorChip's `if/else if`
  chain over `error.content.code` collapsed to a `_ERROR_KEYS:
  Record<string, Keys<"mission">>` lookup table; the
  `Record<string, unknown>` cast on `detected_protections` was
  redundant (the SSE protocol's `error.content` already carries
  `[k: string]: unknown`). The original
  `test_browser_slot_serializes_at_capacity` passed at any
  concurrency level (it just counted entries/exits); rewrote it
  with an `in_flight` counter that asserts `peak <= 8` AND
  `peak == 8` so the saturation is genuinely verified. Other
  surprises: (a) `result.all_messages()` in Pydantic AI 1.44
  returns `ModelRequest` instances whose `.parts` carry
  `ToolReturnPart` with `.content` holding the original Pydantic
  model instance — `isinstance(part.content, _OK_TYPES)` works
  directly. (b) The `@observe` Langfuse decorator strips
  return-type info, so the three `@agent.tool` wrappers in
  `agent.py` re-bind through annotated locals (`result:
  HttpScrapeResult = await scrape_http_impl(...)`) for mypy. (c)
  `code-reviewer` wrote `CODE_REVIEW.md` to the repo root despite
  the project-memory rule against it; a SECURITY WARNING fired
  in the agent's response and the file was deleted before
  staging. Lesson: future agent-driven reviews need an explicit
  "do NOT write CODE_REVIEW.md to repo root" instruction since
  the agent's default behavior is to write it. (d) The original
  `Spec 09` filename in tracker references was
  `specs/09-stealth-tier.md` (shorthand); the actual file is
  `specs/09-stealth-and-dynamic-tier-tools.md` — fixed throughout.
  Four named-agent gates ran: scrape-pipeline-doctor (PASS — all
  invariants hold; SSE ordering soft concern noted as
  spec-prescribed), prompt-engineer (PASS — verbatim system
  prompt match), llm-cost-guard (PASS — bounded retries,
  `max_tokens=2048` on both providers; mission-level deadline
  guard tracked as Open Question 12), code-reviewer (Approve).
  **Verification gate**: `pnpm exec turbo run lint format:check
  typecheck test build` exits 0; pytest 63 passed / 14 skipped;
  Vitest 30 passed (5 test files including the new
  `widgets/task-lane-card/result-preview.test.tsx` with 9 cases).
  Next: Spec 10.
