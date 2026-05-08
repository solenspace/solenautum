<div align="center">

# Autumn

**A concurrent AI scraping agent. Submit URLs or describe what you need; Autumn finds them, scrapes them in parallel, and streams results in real time.**

[Quickstart](#quickstart) · [How it works](#how-it-works) · [Architecture](#architecture) · [Development](#development) · [License](#license)

[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm--NC--1.0.0-1A1612?style=flat-square)](./LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Node 22](https://img.shields.io/badge/node-22-339933?style=flat-square&logo=node.js&logoColor=white)](https://nodejs.org/)
[![Last commit](https://img.shields.io/github/last-commit/solenspace/solenautum?style=flat-square)](https://github.com/solenspace/solenautum/commits/main)
[![Issues](https://img.shields.io/github/issues/solenspace/solenautum?style=flat-square)](https://github.com/solenspace/solenautum/issues)
[![Built with: Pydantic AI · FastAPI · Next.js 16](https://img.shields.io/badge/built_with-Pydantic_AI_·_FastAPI_·_Next.js_16-1A1612?style=flat-square)](#architecture)

</div>

---

Most agentic scrapers serialize: every tool call waits for the previous one. Autumn doesn't. A 10-URL mission opens 10 concurrent tasks inside a single `asyncio.TaskGroup`, each picking the right scraping tier (HTTP, stealth, dynamic browser) for the site it's hitting. Total wall-clock time is the slowest single task, not the sum of all of them.

The agent runs on a Pydantic AI ReAct loop with typed tool I/O and a retry budget that doesn't compound. The LLM stack is OpenRouter's `gpt-oss-120b:free` with Groq `llama-3.3-70b-versatile` as a 429/5xx fallback — both free tier. Tavily handles URL discovery in description mode. Cloudflare R2 holds gzipped HTML snapshots; Neon Postgres holds metadata, parsed markdown, and adaptive selector caches. Langfuse traces every span from request 1.

Self-hostable on Vercel + Fly.io + Neon + R2 + Clerk + Langfuse — every component has a free tier that fits a personal deployment.

## What's inside

- ✅ **URL mode** — paste 1–20 URLs, Autumn scrapes them concurrently
- ✅ **Description mode** — describe what you need, Autumn discovers URLs (Tavily) and surfaces an approval gate before scraping
- ✅ **Three scraping tiers** — HTTP (Scrapling `AsyncFetcher` + Crawl4AI markdown), stealth (Cloudflare Turnstile bypass), dynamic (Playwright). The agent escalates on detected failure.
- ✅ **Concurrent execution** — `asyncio.TaskGroup` per mission with structured cancellation, no detached tasks. Tiered semaphores cap HTTP at 20/mission and browser at 3/mission.
- ✅ **Resumable SSE** — multiplexed per-mission stream with `Last-Event-ID` resume + 200-event ring buffer. Survives mobile reconnects without losing or duplicating events.
- ✅ **Adaptive selectors** — Scrapling `auto_save=True`/`adaptive=True` keyed by `(domain, purpose)`, persisted to Postgres with an LRU hot-path cache. Selectors saved during run N are reused during run N+1 without manual reconfiguration.
- ✅ **Pydantic AI typed agent** — `Agent[Deps, ResultType]`, tool I/O validation, bounded retry decorators, single output schema enforced on every run
- ✅ **Langfuse observability** — traces wired from request 1, `mission_id`/`task_id` propagated into every span, retries and provider switches recorded
- ✅ **Multi-tenant isolation** — Clerk JWT verification, request-scoped user context, Postgres row-level security on `missions` and `tasks` as defense in depth
- ✅ **Safety guards** — SSRF protection (private-network blocklist), `robots.txt` honor with attributable per-mission override, per-user rate limit (60/min, 1000/day)
- ✅ **Master-detail UI** — dense lane stack with per-task LLM summaries in the aside, hostname-grouped approval gate, smooth motion tokens, `prefers-reduced-motion` honored
- ✅ **Pluggable interfaces** — `SearchProvider` (Tavily today, Exa/Brave behind one config swap) and `LLMProvider` (OpenRouter primary, Groq fallback, vLLM tomorrow)
- ✅ **Free-tier self-hosting** — Vercel hobby + Fly.io free + Neon free + R2 free + Clerk free + Langfuse free, no credit card required to run a personal instance

## How it works

A mission is the unit of work. Submitting one walks through five stages:

1. **Submit.** The web app posts to its BFF route with the user's Clerk JWT. The BFF proxies to the FastAPI backend, which writes a `missions` row and one `tasks` row per URL, both in `pending`.
2. **Connect.** The web opens an SSE connection scoped to `mission_id`. The connection survives mid-stream drops via `Last-Event-ID` resume; the api keeps a 200-event ring buffer per mission for 60 seconds past terminal so a reconnecting client doesn't miss the `done`.
3. **Run.** The api enters a single `asyncio.TaskGroup` and spawns one coroutine per task. Each coroutine acquires a tier semaphore (HTTP or browser) before its scrape runs, so a 20-URL mission never thrashes the host. Pydantic AI drives the per-task ReAct loop: pick a scrape tool, call it, validate the typed response, escalate to the next tier on failure, return a `MissionResult`.
4. **Stream.** Each task emits `task_start`, then a stream of `token` (LLM reasoning) and `tool_start`/`tool_end` chips, then exactly one terminal event (`task_end` with status, or `error`). Mission-level events sit alongside (`url_discovered`, `discovery_complete` for description mode, `selector_recovered` when an adaptive selector recovers from DOM drift). Every event carries a monotonic `seq` so resume is loss-free.
5. **Persist.** On terminal, the runner writes parsed markdown to Postgres, the gzipped HTML snapshot to R2, the agent's one-paragraph summary to `tasks.summary`, and (if a new selector was learned) the selector payload to `saved_selectors`. The mission's rolled-up status flips: `succeeded` if any task succeeded, `cancelled` if every non-cancelled task was cancelled, `failed` only when no tasks succeeded and none were cancelled.

The full lifecycle is traced in Langfuse end-to-end, with mission and task IDs on every span.

## Quickstart

### Local dev

Requires Node 22, Python 3.12, [pnpm](https://pnpm.io/) 11+, [uv](https://docs.astral.sh/uv/), and a Postgres 16+ instance (local or Neon).

```bash
git clone https://github.com/solenspace/solenautum.git
cd solenautum

# install JS deps + sync Python deps
pnpm install
cd apps/api && uv sync && cd ../..

# copy env templates and fill in keys (see table below)
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env.local

# create the database, then run migrations
psql -c "create database autumn_dev"
cd apps/api && uv run alembic upgrade head && cd ../..

# start everything (turbo runs api on :8000 and web on :3000)
pnpm dev
```

Sign in via Clerk, paste a URL, run a mission. Or press <kbd>⌘</kbd>+<kbd>⇧</kbd>+<kbd>D</kbd> for description mode.

### Required environment variables

| Key | Where to get it | Required? |
| --- | --- | --- |
| `DATABASE_URL` | Postgres connection string (`postgresql+asyncpg://...`) | yes |
| `CLERK_PUBLISHABLE_KEY` | [Clerk dashboard](https://dashboard.clerk.com/) → API keys | yes |
| `CLERK_SECRET_KEY` | Clerk dashboard → API keys | yes |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) — free tier covers `gpt-oss-120b:free` | yes |
| `TAVILY_API_KEY` | [tavily.com](https://tavily.com/) — free tier covers description mode | yes |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com/keys) — fallback when OpenRouter 429s | optional |
| `BLOB_STORE_BACKEND` | `local` for dev, `r2` for production | yes |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | [cloud.langfuse.com](https://cloud.langfuse.com/) — traces every agent run | optional |
| `CLERK_WEBHOOK_SIGNING_SECRET` | Clerk → Webhooks; only needed for production user provisioning | optional |

### Self-host

Free-tier hosting fits in five services: Vercel (web), Fly.io or Render (api), Neon (Postgres), Cloudflare R2 (snapshots), Clerk (auth). A deploy walkthrough lives in `docs/deploy.md` (TBD; track [#deploy-docs](https://github.com/solenspace/solenautum/issues)).

## Architecture

```
.
├── apps/
│   ├── web/           Next.js 16 + React 19 + Tailwind 4 (FSD layered: shared / entities / features / widgets / app)
│   └── api/           FastAPI + Pydantic AI + Scrapling + Crawl4AI (router → agent → tools → persistence)
├── packages/
│   └── sse-protocol/  JSON Schema → generated TS types + pydantic models (single source of truth for the SSE wire format)
└── context/           project-overview, architecture, ui-context, code-standards, ai-workflow-rules, progress-tracker
```

| Layer | Tech |
| --- | --- |
| Web | Next.js 16 (Turbopack) + React 19 + TypeScript strict + Tailwind 4 + shadcn/ui |
| API | FastAPI + Python 3.12 + uv + Pydantic AI 1.44 |
| LLM | OpenRouter (`gpt-oss-120b:free`) primary, Groq (`llama-3.3-70b-versatile`) fallback |
| Search | Tavily (pluggable behind `SearchProvider`) |
| Scraping | Scrapling 0.2.99 (HTTP / stealth / dynamic) + Crawl4AI 0.8.6 (markdown extraction) |
| DB | Neon Postgres + sqlmodel + alembic + Postgres RLS |
| Blob | Cloudflare R2 (S3-compatible via boto3) |
| Streaming | SSE + `Last-Event-ID` + per-mission ring buffer |
| Auth | Clerk + middleware on web + JWKS verification on api |
| Observability | Langfuse |

The full picture, including 12 architectural invariants, lives in [`context/architecture.md`](./context/architecture.md). The product story is in [`context/project-overview.md`](./context/project-overview.md). The design language and writing rules are in [`context/ui-context.md`](./context/ui-context.md).

## Development

The repo follows [gitflow](https://nvie.com/posts/a-successful-git-branching-model/). Two long-lived branches: `main` (production) and `development` (integration). All work happens on a short-lived branch cut from `development`.

```bash
git checkout development && git pull --ff-only
git checkout -b feature/<short-name>      # or fix/, chore/, docs/
# implement, commit, push
gh pr create --base development            # merge once green
```

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) — `<type>(<scope>): <imperative summary>`. Allowed types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `build`, `ci`, `perf`, `style`, `revert`. The `commit-msg` hook (lefthook) enforces it.

Verification gates before opening a PR:

```bash
pnpm typecheck   # turbo run typecheck across web, api, sse-protocol
pnpm test        # vitest + pytest
pnpm build       # next build + sse-protocol codegen
```

Promotion to `main` happens via a release PR (`development → main`) when a unit of work is shippable.

## What it isn't

Autumn is intentionally narrow. The following are out of scope and won't be added:

- Billing, metering, paid plans, or usage-based pricing
- Akamai / DataDome / PerimeterX bypass — the agent returns `site_not_supported` with detected protections listed
- Cross-mission orchestration (no "every Monday, scrape these")
- Distributed workers, Celery, Redis, or external queue infrastructure
- Browser extensions, desktop clients, or mobile apps
- Residential proxy rotation, Bright Data, IPRoyal
- User-submitted custom scraping scripts (sandbox surface area we won't carry)
- Public sharing of scraped results
- Multi-locale i18n at MVP — the framework is wired, but only English ships

If you need any of these, Autumn isn't the right tool. The codebase is small enough to fork, but see the [License](#license) below before doing so commercially.

## License

[PolyForm Noncommercial 1.0.0](./LICENSE).

You may use, modify, and share Autumn for personal, educational, research, and charitable purposes. **Commercial use is forbidden** — including, but not limited to, hosting Autumn as a service, using it in a for-profit business workflow, or selling derivatives. The full text and the precise definition of "noncommercial" live in [`LICENSE`](./LICENSE).

For commercial licensing, open an issue or reach the maintainer directly.
