# Progress Tracker

Update this file after every meaningful implementation change. The
progress tracker is the only file expected to mutate continuously
through the build; it is also the file the agent reads first when
resuming a session.

## Current Phase

- Implementation phase begins.

## Current Goal

- Implementing `specs/04-clerk-auth-and-security-foundation.md`.

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

## In Progress

- `specs/04-clerk-auth-and-security-foundation.md` — to begin next
  session.

## Next Up

- Implement `specs/04-clerk-auth-and-security-foundation.md` (Clerk
  middleware + protected routes + Postgres RLS scaffolding). The
  remaining specs follow in numbered order; each spec's `Done when`
  checklist gates progress to the next.

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
