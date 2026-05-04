# Autumn

## Overview

Autumn is a concurrent AI scraping agent. A signed-in user submits a
mission in one of two modes: **URL mode** (paste one or more URLs and
let Autumn scrape them) or **description mode** (describe what you
need and Autumn finds the URLs first, then scrapes them in parallel).
The agent runs on a Pydantic AI ReAct loop with three scraping tiers
(HTTP + markdown extraction, Cloudflare-bypass stealth, full browser
dynamic) and streams per-task progress over a multiplexed SSE channel
that survives mobile reconnects. Autumn exists to fill the concurrency
gap left by `agentic-flagship`, which runs scraping tools sequentially.

## Goals

1. A 10-URL mission scrapes all 10 URLs concurrently without serializing
   on tool calls; total wall-clock time approximates the slowest single
   task, not the sum of all tasks.
2. Description-mode missions resolve from a free-text query to a
   validated, user-approved URL list in under 10 seconds for typical
   queries (≤20 URLs).
3. Adaptive selectors saved during run N are reused during run N+1
   on the same `(domain, purpose)` pair without manual reconfiguration.
4. SSE clients render N parallel task lanes from a single mission stream
   and resume mid-stream from `Last-Event-ID` after a 30-second network
   drop without losing events.
5. Time-to-first-token under 2 seconds for HTTP-tier tasks on a warm
   in-memory cache.

## Core User Flow

### URL mode

1. User signs in via Clerk and lands on the missions dashboard.
2. User opens a new mission, pastes one or more URLs (1–20), and submits.
3. The web app posts to its BFF route, which proxies to the FastAPI
   backend with the user's Clerk JWT.
4. The backend writes the `missions` and per-URL `tasks` rows to Neon
   in `pending` status, then promotes the mission to `running`.
5. A new SSE connection opens; the agent begins emitting per-task
   `task_start` events with assigned tier (HTTP by default).
6. Each task runs concurrently inside the mission's `asyncio.TaskGroup`,
   bounded by tier semaphores. Tool calls are streamed as collapsed
   chips; reasoning streams dimmed; scraped markdown previews high-
   contrast in the lane body.
7. Each task emits exactly one terminal event (`task_end` with status
   or `error`); the lane auto-collapses on success.
8. When all tasks terminate, the mission emits `done` and the row is
   marked `succeeded`/`failed`/`cancelled`.

### Description mode

1. User signs in and opens a new mission, switches to description mode.
2. User types a free-text query (1–2000 chars) and submits.
3. The agent calls `discover_urls` (Tavily), emits `url_discovered`
   events, capped per-mission at 1 search call and 20 results.
4. The web shows the **URL approval gate**: discovered URLs default-
   checked, grouped by domain, inline-editable on hover, with an
   "auto-approve future runs" toggle.
5. User approves; the mission proceeds exactly as URL mode from
   step 4 above.

## Features

### Mission Input
- URL mode (1–20 URLs per mission)
- Description mode with Tavily-backed URL discovery
- Per-mission auto-approve toggle for discovered URLs
- Cmd+K command palette, Cmd+Enter submit, Esc cancel

### URL Discovery
- Tavily as the default `SearchProvider`
- Pluggable interface (Exa/Brave/SerpAPI behind a config swap)
- Per-mission cost cap (max 1 search call, max 20 results)
- `url_discovered` events streamed to the client for live preview

### Tiered Scraping
- **HTTP tier** — Scrapling `AsyncFetcher` piped through Crawl4AI for
  LLM-ready markdown
- **Stealth tier** — Scrapling `AsyncStealthySession` with Cloudflare
  Turnstile/Interstitial bypass
- **Dynamic tier** — Scrapling `AsyncDynamicSession` (Playwright) for
  JS-rendered pages
- The agent prefers HTTP first, escalates to stealth/dynamic on
  detected failure

### Concurrency
- `asyncio.TaskGroup` per mission with structured cancellation
- Tiered semaphores: HTTP per-mission 20 / global 60; browser per-
  mission 3 / global 8
- No detached `asyncio.create_task()` outside a mission's group

### Result Persistence
- Mission/task metadata in Neon Postgres with row-level security
- Parsed markdown stored in Neon (queryable, ~10× smaller than HTML)
- Raw HTML snapshots gzipped to Cloudflare R2 with signed retrieval
  URLs
- 30-day snapshot retention; parsed markdown retained until user
  deletion

### Adaptive Selectors
- Scrapling `auto_save=True` + `adaptive=True` namespaced by
  `(domain, selector_purpose)`
- LRU hot-path cache (1k entries) over a covering Neon index
- `selector_recovered` events surface a "recovered N times" indicator
  per task lane

### Observability
- Langfuse tracer wired from the first agent run
- `mission_id` / `task_id` propagated into every span
- Per-mission cost surfaced in the sidebar; per-task breakdown on hover

### Auth
- Clerk sign-in/sign-up + middleware on web
- JWT verified via JWKS on api; user_id extracted to a request-scoped
  context
- Postgres RLS as defense-in-depth on `missions` and `tasks`
- Per-user gateway rate limit (60/min, 1000/day)

### Streaming UX
- Multiplexed SSE with per-mission `mission_id` and per-task `task_id`
- Monotonic `seq` on every event, server-side ring buffer (last 200)
- Mobile reconnect with `Last-Event-ID` resume; visible "reconnecting…"
  pill
- Stacked collapsible task lanes; aggregate progress in a sticky
  header

## Scope

### In Scope

- URL-mode and description-mode missions (1–20 URLs each)
- HTTP, Stealth, and Dynamic scraping tiers
- Cloudflare anti-bot bypass via Scrapling Stealth
- Concurrent task execution with tiered semaphores
- Clerk-authenticated per-user accounts and ownership
- Tavily URL discovery with provider abstraction
- Per-tier markdown / structured extraction
- Adaptive selector persistence and reuse
- Multiplexed SSE with `Last-Event-ID` resume
- Langfuse observability from day one
- Postgres RLS and gateway rate limiting
- `robots.txt` honor with attributable per-mission user override
- English-only i18n (framework wired, single locale)
- Vercel + Fly.io/Render + Neon + R2 + Clerk + Langfuse free-tier
  hosting

### Out of Scope

- Billing, metering, or paid plans
- **Akamai / DataDome / PerimeterX bypass** (returns
  `site_not_supported` with detected protections listed)
- Cross-mission orchestration (e.g., "every Monday, scrape these")
- Distributed workers, Celery, Redis, or external queues
- Browser extensions or desktop clients
- Paid Scrapling sponsor features
- Multi-locale i18n at MVP (framework only)
- Residential proxy rotation, Bright Data, IPRoyal
- User-submitted custom scraping scripts
- Public sharing of scraped results

## Success Criteria

1. A signed-in user submits a 10-URL mission in URL mode and sees all
   10 task lanes stream concurrently with tier badges, tool-call chips,
   and a sticky aggregate header showing live progress.
2. The mission survives a 30-second forced disconnect: the SSE
   reconnects, `Last-Event-ID` is honored, and no events are lost or
   duplicated in the rendered lanes.
3. Parsed markdown for every task lands in `tasks.parsed_markdown` in
   Neon; gzipped raw HTML for every task lands at
   `autumn-snapshots/{user_id}/{mission_id}/{task_id}.html.gz` in R2.
4. The mission row reaches `succeeded` only when every task emits
   exactly one terminal event; orphan tasks fail the verification gate.
5. A second run on the same domain triggers `selector_recovered`
   events for cached `(domain, purpose)` pairs without re-discovering
   selectors.
6. A description-mode mission renders the URL approval gate with
   default-checked URLs grouped by domain, and after approval proceeds
   exactly as URL mode.
7. A second user in the same deployment cannot read or list the first
   user's missions, even with a forged WHERE clause — Postgres RLS
   policies block the cross-tenant query.
8. The full Langfuse trace for a mission contains every tool call,
   retry, and provider switch with `mission_id`/`task_id` metadata.
