# 08 — web-shell-and-stream-consumer

## Goal

Stand up the dense, power-user web shell that consumes the SSE
stream from Spec 07. After this spec, a signed-in user lands on
`/missions`, sees their mission list in a left sidebar grouped by
status, types a URL into the persistent top-bar input, hits
`Cmd+Enter`, and watches the streamed task lane render in a
right-side slide-over with a three-tier visual hierarchy
(reasoning → tool chips → result preview). The Cmd+K command
palette and the basic keyboard shortcuts are wired. The UI feels
like Linear / Vercel / Cron — not like a generic shadcn install.

## Dependencies

- `specs/01–03` — workspaces, lint, hooks
- `specs/04` — Clerk middleware, `/(auth)` routes, the placeholder
  `/missions/page.tsx` that this spec **replaces**
- `specs/05` — `MissionRepository` + `Status` enum (read via a new
  `/missions` JSON endpoint)
- `specs/06` — `@autumn/sse-protocol` package supplies the typed
  `SseEvent` discriminated union
- `specs/07` — the `/run-mission?url=...` SSE endpoint and the
  ring-buffer + `Last-Event-ID` resume protocol on the api side

## Design Decisions

### Density posture (folded into every UI choice below)

The product is a **tool**, not a marketing surface. Reference
aesthetic: Linear / Vercel dashboard / Cron / Stripe. Generic
shadcn-out-of-the-box is forbidden. Concrete tactics — applied
across every component:

- Compact rows: `h-7` / `h-8` everywhere; `h-9` only on the
  primary CTA in the top bar. Never `h-10` or larger.
- Status pills: 18-20px tall, `text-[11px]`, `font-medium`,
  `px-1.5`, `rounded`, **with a 6px colored dot prefix**, no
  full-fill background.
- Two-tone borders: `border-border/50` on internal dividers,
  `border-border` on container edges.
- Type scale: `text-[13px]` body, `text-xs` (12px) secondary,
  `text-[11px]` metadata; `font-mono tabular-nums` for IDs,
  durations, URLs, timestamps.
- Spacing: `gap-1.5` / `gap-2` between inline items inside rows;
  `gap-3` between distinct row groups; never `gap-4` inside rows.
- Inputs / chips: `px-2 py-1`; full-width inputs `px-3`.
- Radius: `rounded-md` everywhere; `rounded-lg` only on cards
  and dialogs.
- Color usage: `text-muted-foreground` for ~60% of all text;
  `text-foreground` reserved for active/primary content.
- Elevation: `ring-1 ring-border/50` instead of `shadow-md`.
- Focus: `focus-visible:ring-2 ring-ring/40` — never default
  browser outline.
- Hover/active: `data-[state=open]:bg-accent/40` rather than full
  background swap.

### Stack and layout

- **Tailwind 4 + shadcn/ui `new-york` style**, with project tokens
  from `context/ui-context.md` driving the theme. shadcn's CSS
  variables are bridged to our tokens (e.g., `--primary`,
  `--ring`, `--destructive` map to our `--accent-primary`,
  `--ring-focus`, `--state-error`).
- **`--radius` is set to `0.375rem` (md)** — not the shadcn
  default `0.5rem`.
- **Lift dense composite blocks from shadcn/ui v4 blocks**:
  `sidebar-07` for the left sidebar shape, `dashboard-01` for the
  top-bar + content split. Adapt to FSD; do not import them as a
  black box.
- **Mission detail uses a slide-over from the right**, not a
  separate route. Click a mission row → slide-over opens; click
  outside or `Esc` → closes. URLs are not shareable in this spec
  — that's fine for MVP, deliberately simpler.
- **Single `/missions` page** is the only authenticated route at
  this stage. The placeholder page from Spec 04 is replaced.
- **Top-bar URL input is persistent across the entire app shell**
  — submit a mission from anywhere with `Cmd+Enter`.
- **Three-tier streaming hierarchy** in the task lane:
  - **Reasoning**: `text-xs text-muted-foreground/70 leading-relaxed`,
    `border-l-2 border-border/50 pl-3`. Append in batches of 4–6
    tokens with a 60ms `transition-opacity`. **No italic** —
    Geist's display weight at small sizes reads off when italic.
  - **Tool chips**:
    `inline-flex h-6 items-center gap-1.5 rounded border border-border/50 bg-muted/40 px-1.5 text-[11px] font-mono`
    with a leading status dot.
  - **Result preview**: `text-sm text-foreground rounded-md border bg-card p-3`,
    mono only for URLs/IDs.
- **No per-token fade-in** on tokens. Batch-append every 4–6
  tokens with a single 60ms transition. Per-token fades read as
  flashy on dense UIs.

### Form and routing

- **URL submission** uses **plain controlled state** + a `zod`
  schema parsed on submit. One input, one button. `react-hook-form`
  is overkill here; we adopt it in Spec 12 if description-mode's
  multi-field form earns it.
- **Mission detail = slide-over**. No URL sync, no search param.
  Refreshing the page returns the user to the index. We accept
  the no-shareability tradeoff for Spec 08.
- **Resume protocol on slide-over open**: `use-mission-stream`
  reads `localStorage['autumn:mission:<id>:seq']` if present and
  the mission's status (fetched from `/api/missions/<id>`) is
  `RUNNING`. If both, it opens SSE with `Last-Event-ID: <seq>`.
  Otherwise it opens fresh; or, for terminal missions, it skips
  SSE and renders the persisted state via the JSON endpoint.

### Command palette

- **`cmdk`** (Vercel's command palette primitive used by shadcn).
  Mounted at the app shell level; toggled with `⌘K` /
  `Ctrl+K`.
- **Sections** (in this order):
  1. **Recent** — last 3 mission URLs (mono, truncated)
  2. **Actions** — `New URL mission ⌘N`, `Toggle reasoning ⌘.`,
     `Toggle sidebar ⌘B`, `Cancel mission Esc`
  3. **Go to** — `Missions`
  4. **Account** — `Sign out`
- Section headers:
  `text-[11px] uppercase tracking-wide text-muted-foreground/70`.
- Each item: 32px tall, leading icon, label, trailing kbd chip.

### Keyboard shortcuts (registered at the shell level)

Per `context/ui-context.md`'s shortcut table:

| Shortcut | Action |
|---|---|
| `/` | Focus the top-bar URL input |
| `⌘K` | Open command palette |
| `⌘↩` | Submit current form (URL input or palette) |
| `Esc` | Close slide-over / palette / cancel mission |
| `⌘B` | Toggle sidebar |
| `⌘.` | Toggle reasoning visibility on the open lane |
| `⌘⇧N` | New mission (focus URL input + clear) |
| `?` | Open shortcut help dialog |

Shortcuts live in `apps/web/shared/keyboard/`. The shell mounts a
single global handler; per-feature handlers register and
deregister on mount.

### Empty states (the **bad** ones to avoid)

The empty mission list does **not** show illustrations, mascots,
marketing copy, or a giant centered card. Pattern:

- Vertically centered in the lane region only (not the viewport)
- `max-w-md` panel, left-aligned
- Heading: `No missions yet`
- One-line copy: `Paste a URL above or press ⌘N`
- One inline `<kbd>` chip showing `⌘N`
- No buttons (the action is already visible in the top bar)

### i18n

All user-facing strings flow through `t(namespace, key, params?)`
per `context/code-standards.md`. Existing namespaces
(`common`, `mission`, `validation`, `message`, `agent`) are reused;
no new namespaces in this spec. Validators return keys; UI
resolves.

References:
- `context/architecture.md` — System Boundaries (web), Invariants
  4, 5, 7
- `context/ui-context.md` — full Voice & Copy and Color tokens
- `context/code-standards.md` — TypeScript, Next.js, i18n,
  Auth integration
- Skills: `next-best-practices`, `vercel-composition-patterns`,
  user-level `react-architecture`
- Reference patterns: Linear product UI, Vercel dashboard,
  shadcn/ui v4 blocks `sidebar-07` and `dashboard-01`

## Implementation

### A. Tailwind 4 + shadcn install

From `apps/web/`:

```bash
pnpm dlx shadcn@latest init --style=new-york --base-color=neutral
```

After init, edit `apps/web/components.json` to set
`tailwind.cssVariables: true`, `style: "new-york"`, and the
default radius:

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "tsx": true,
  "tailwind": {
    "config": "",
    "css": "app/globals.css",
    "baseColor": "neutral",
    "cssVariables": true
  },
  "aliases": {
    "components": "@/components",
    "ui": "@/components/ui",
    "utils": "@/shared/utils/cn",
    "hooks": "@/shared/hooks"
  },
  "iconLibrary": "lucide"
}
```

Add the components we need now (each one runs the shadcn CLI):

```bash
pnpm dlx shadcn@latest add button input dialog sheet command kbd \
  separator scroll-area sidebar tooltip
```

Edit `apps/web/app/globals.css` to bridge our tokens to shadcn's
CSS variables. The bridge maps `--background` → our `--bg-base`,
`--card` → `--bg-surface`, `--popover` → `--bg-surface-elevated`,
`--primary` → `--accent-primary` (which is `#000000` in light mode
and `#FFFFFF` in dark mode per the bone+narrow-black palette in
`context/ui-context.md`), `--ring` → `--ring-focus`,
`--destructive` → `--state-error`, etc. **Override `--radius` to
`0.375rem`** in the same file.

**Tailwind 4 syntax — non-negotiable**:

- Use `@import "tailwindcss";` at the top of `globals.css`. Do
  **not** use `@tailwind base; @tailwind components; @tailwind utilities;`
  — those directives were removed in Tailwind 4.
- Install the new PostCSS plugin: `@tailwindcss/postcss` (not the
  legacy `tailwindcss` package's PostCSS plugin).
- Replace any `shadow-sm` class → `shadow-xs`. Tailwind 4 renamed
  the smallest shadow utility.
- Replace any `outline-none` class → `outline-hidden`. Tailwind 4
  renamed the outline-removal utility (the previous name shipped
  a real outline by accident).
- The `@theme` block is the canonical config; CSS variables in
  `@theme` map directly to Tailwind utility classes
  (`bg-bg-base`, `text-text-primary`, etc.).

### B. App shell — `apps/web/app/(app)/layout.tsx`

```tsx
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

import { TopBar } from "@/widgets/top-bar";
import { MissionSidebar } from "@/widgets/mission-sidebar";
import { CommandPalette } from "@/widgets/command-palette";
import { KeyboardShortcuts } from "@/shared/keyboard";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { userId } = await auth();
  if (!userId) redirect("/sign-in");

  return (
    <div className="flex min-h-dvh flex-col bg-background text-foreground">
      <TopBar />
      <div className="flex flex-1 overflow-hidden">
        <MissionSidebar />
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
      <CommandPalette />
      <KeyboardShortcuts />
    </div>
  );
}
```

`(app)` is a route group — it does not affect the URL.
`/missions` lives under it; future authed routes do too.

### C. Top bar — `apps/web/widgets/top-bar/`

```tsx
"use client";

import { Globe2 } from "lucide-react";
import { useId, useState } from "react";

import { Kbd } from "@/components/ui/kbd";
import { useT } from "@/shared/i18n";
import { useSubmitMission } from "@/features/run-mission";
import { useShortcut } from "@/shared/keyboard";

export function TopBar() {
  const t = useT();
  const inputId = useId();
  const [url, setUrl] = useState("");
  const { submit, isSubmitting, error } = useSubmitMission();

  useShortcut("/", () => {
    document.getElementById(inputId)?.focus();
  });

  return (
    <header className="flex h-11 items-center gap-2 border-b border-border/50 bg-background px-3">
      <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
        Autumn
      </span>
      <div className="ml-3 flex h-8 flex-1 items-center gap-2 rounded-md border border-border/50 bg-card pl-2 pr-1.5">
        <Globe2 className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
        <input
          id={inputId}
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={t("mission", "urlPlaceholder")}
          autoComplete="off"
          spellCheck={false}
          className="flex-1 bg-transparent font-mono text-[13px] outline-hidden placeholder:text-muted-foreground/60"
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              void submit(url).then(() => setUrl(""));
            }
          }}
          disabled={isSubmitting}
        />
        <Kbd>⌘↩</Kbd>
      </div>
      {error ? (
        <span className="text-[11px] text-destructive">
          {t("validation", error)}
        </span>
      ) : null}
    </header>
  );
}
```

The top bar height is **44px** (`h-11`). The URL input is 32px
(`h-8`) so it sits inside with breathing room. The `<Kbd>`
component is a shadcn primitive showing the keyboard hint inline.

### D. Mission sidebar — `apps/web/widgets/mission-sidebar/`

A `Sidebar` (lifted from shadcn block `sidebar-07`) renders a
collapsible left panel with mission rows grouped by status:
`Running`, `Queued`, `Completed`. Each row is 32px (`h-8`),
displays:

- 6px status dot (color from `--state-success`/`--state-error`/
  `--accent-primary`/`--text-muted` based on status)
- 8-character mission id prefix in mono
- truncated URL (mono, `flex-1 truncate`)
- 11px relative time on the right (`tabular-nums`)

Click a row → opens the slide-over with that mission's detail.

```tsx
"use client";

import { Sidebar, SidebarHeader, SidebarContent, SidebarGroup } from "@/components/ui/sidebar";
import { useMissions } from "@/features/run-mission";
import { MissionRow } from "./mission-row";
import { useT } from "@/shared/i18n";

const GROUPS = ["running", "pending", "succeeded", "failed", "cancelled"] as const;

export function MissionSidebar() {
  const t = useT();
  const { byStatus } = useMissions();

  return (
    <Sidebar className="border-r border-border/50">
      <SidebarHeader className="px-3 py-2 text-[11px] uppercase tracking-wide text-muted-foreground/70">
        {t("mission", "yourMissions")}
      </SidebarHeader>
      <SidebarContent>
        {GROUPS.map((status) => {
          const items = byStatus[status] ?? [];
          if (items.length === 0) return null;
          return (
            <SidebarGroup key={status}>
              <div className="px-3 pt-2 text-[11px] uppercase tracking-wide text-muted-foreground/70">
                {t("mission", `status_${status}`)}
              </div>
              {items.map((m) => (
                <MissionRow key={m.id} mission={m} />
              ))}
            </SidebarGroup>
          );
        })}
      </SidebarContent>
    </Sidebar>
  );
}
```

### E. Mission slide-over — `apps/web/widgets/mission-detail/`

Uses shadcn `Sheet` (Radix Dialog under the hood) sliding in from
the right. Width: `w-full sm:max-w-2xl`. Header shows the mission
URL + status pill + Esc kbd. Body renders a single `TaskLaneCard`
(Spec 11 will turn this into a stack).

```tsx
"use client";

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { TaskLaneCard } from "@/widgets/task-lane-card";
import { useMissionStore } from "@/features/run-mission";
import { useShortcut } from "@/shared/keyboard";

export function MissionDetailSlideover() {
  const { openMissionId, closeMission } = useMissionStore();
  useShortcut("Escape", () => openMissionId && closeMission());

  return (
    <Sheet open={!!openMissionId} onOpenChange={(v) => !v && closeMission()}>
      <SheetContent side="right" className="w-full sm:max-w-2xl border-l border-border/50">
        <SheetHeader className="border-b border-border/50 pb-2">
          <SheetTitle className="font-mono text-[13px] truncate">
            {openMissionId}
          </SheetTitle>
        </SheetHeader>
        {openMissionId ? <TaskLaneCard missionId={openMissionId} /> : null}
      </SheetContent>
    </Sheet>
  );
}
```

The sheet renders inside `apps/web/app/(app)/missions/page.tsx`.

### F. `useSubmitMission` and `useMissions` — `apps/web/features/run-mission/`

#### `apps/web/features/run-mission/use-submit-mission.ts`

```tsx
"use client";

import { z } from "zod";
import { useState } from "react";

import { useMissionStore } from "./store";

const urlSchema = z
  .string()
  .min(1, "urlRequired")
  .max(2048, "urlTooLong")
  .url("urlInvalid");

export function useSubmitMission() {
  const open = useMissionStore((s) => s.openMission);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);

  async function submit(input: string) {
    setError(null);
    const parsed = urlSchema.safeParse(input.trim());
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "urlInvalid");
      return;
    }
    setSubmitting(true);
    try {
      // Server route opens SSE; we proxy through a BFF route to
      // attach the Clerk JWT and forward the stream.
      const response = await fetch(
        `/api/missions?url=${encodeURIComponent(parsed.data)}`,
        { method: "POST" },
      );
      if (!response.ok) {
        setError("missionFailed");
        return;
      }
      const { missionId } = (await response.json()) as { missionId: string };
      open(missionId);
    } finally {
      setSubmitting(false);
    }
  }

  return { submit, isSubmitting, error };
}
```

The validation errors are returned as **i18n keys**, not strings,
per `context/code-standards.md`. The top-bar component resolves
them via `t("validation", error)`.

#### `apps/web/features/run-mission/store.ts`

A small `zustand` store holds `openMissionId`. Lightweight and
preserves the slide-over state across re-renders. Add `zustand`
to `apps/web/package.json`:

```bash
pnpm --filter @autumn/web add zustand
```

```tsx
import { create } from "zustand";

interface MissionStore {
  openMissionId: string | null;
  openMission: (id: string) => void;
  closeMission: () => void;
}

export const useMissionStore = create<MissionStore>((set) => ({
  openMissionId: null,
  openMission: (id) => set({ openMissionId: id }),
  closeMission: () => set({ openMissionId: null }),
}));
```

#### `apps/web/features/run-mission/use-missions.ts`

Polls `/api/missions` every 5 seconds for the mission list. Spec
14 introduces a smarter cache + WebSocket-style invalidation; this
spec ships polling.

### G. BFF routes (`apps/web/app/api/missions/`)

Two BFF routes proxy the Clerk JWT to the api:

- `POST /api/missions?url=...` — calls api `GET /run-mission?url=...`,
  reads the first event from the SSE response (which is
  `task_start` containing `mission_id`), returns `{missionId}` to
  the caller. The full SSE stream is **not** consumed here —
  `use-mission-stream` opens a separate SSE connection on the
  client side once the slide-over is open.
- `GET /api/missions` — calls api `GET /missions` (a new endpoint
  returning the mission list) and forwards the JSON.

For Spec 08, simplification: the BFF `/api/missions` endpoint
calls the api `/run-mission?url=...` and returns the mission row
created by the runner. Since the runner currently `await`s the
full mission before returning, `POST /api/missions` blocks until
the mission terminates. **This is a known limitation of Spec 07's
runner**; Spec 10 separates mission-start from streaming so the
BFF returns immediately with the `mission_id` and the slide-over
streams from there. For Spec 08, we ship the simple version: the
slide-over opens after the mission completes, showing the
terminal state via a short replay from the api's ring buffer.

A short-form alternative that ships in Spec 08 to match the
streaming demo: introduce a `POST /missions` non-streaming
endpoint on the api that creates the mission row in `RUNNING`
status, kicks off the runner via `asyncio.create_task` (gated by
a TODO marker for Spec 10's TaskGroup-correct refactor), and
returns `{missionId}` immediately. The BFF wraps it. The slide-
over then opens an SSE connection to `/run-mission/<id>/stream`
that attaches to the in-progress mission.

We accept the small **invariant 3 deviation** in Spec 08 —
`asyncio.create_task` outside a TaskGroup — because Spec 10 closes
the gap immediately after. The deviation is annotated in
`progress-tracker.md` as an open item that **must** close in
Spec 10. The `scrape-pipeline-doctor` agent already enforces this;
Spec 10's PR will fail review until the create_task is replaced.

### H. SSE consumer hook — `apps/web/features/run-mission/use-mission-stream.ts`

```tsx
"use client";

import { useEffect, useRef, useState } from "react";

import type { SseEvent } from "@autumn/sse-protocol";

export interface MissionStreamState {
  events: SseEvent[];
  isConnected: boolean;
  reconnecting: boolean;
}

const STORAGE_KEY = (missionId: string) => `autumn:mission:${missionId}:seq`;

export function useMissionStream(missionId: string | null): MissionStreamState {
  const [state, setState] = useState<MissionStreamState>({
    events: [],
    isConnected: false,
    reconnecting: false,
  });
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!missionId) return;

    let cancelled = false;
    const lastSeq = readLastSeq(missionId);

    function open() {
      const url = `/api/missions/${missionId}/stream`;
      // EventSource cannot send custom headers; we encode Last-Event-ID
      // as a query param and the BFF forwards it to the api.
      const fullUrl = lastSeq != null ? `${url}?after=${lastSeq}` : url;
      const es = new EventSource(fullUrl);
      sourceRef.current = es;

      es.onopen = () => {
        if (cancelled) return;
        setState((s) => ({ ...s, isConnected: true, reconnecting: false }));
      };

      es.onerror = () => {
        if (cancelled) return;
        setState((s) => ({ ...s, isConnected: false, reconnecting: true }));
        // EventSource auto-reconnects; we don't recreate manually.
      };

      es.onmessage = (msg) => {
        if (cancelled) return;
        const data = JSON.parse(msg.data) as unknown;
        const parsed = parseSseEvent(data);
        if (parsed == null) return; // unknown type — log + skip
        writeLastSeq(missionId, parsed.seq);
        setState((s) => ({ ...s, events: [...s.events, parsed] }));
      };
    }

    open();

    return () => {
      cancelled = true;
      sourceRef.current?.close();
    };
  }, [missionId]);

  return state;
}

function readLastSeq(id: string): number | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY(id));
    return v == null ? null : Number.parseInt(v, 10);
  } catch {
    return null;
  }
}

function writeLastSeq(id: string, seq: number): void {
  try {
    localStorage.setItem(STORAGE_KEY(id), String(seq));
  } catch {
    // localStorage unavailable; resume won't work but stream still works
  }
}

function parseSseEvent(raw: unknown): SseEvent | null {
  // Generated discriminated union throws on unknown type via discriminator;
  // wrap in try/catch and return null for unrecognized events.
  // Concrete impl: tsoa-style schema-validate or a tiny custom guard.
  // Spec 06's generated types power the type assertion at the call site.
  if (typeof raw !== "object" || raw == null || !("type" in raw)) return null;
  return raw as SseEvent;
}
```

The `EventSource` API does not support custom headers, so
`Last-Event-ID` is encoded as the `?after=<seq>` query parameter.
The BFF route translates `?after=...` into the `Last-Event-ID`
header before forwarding to the api. The api's SSE handler accepts
either source.

The hook intentionally does **not** trigger reconnects manually —
the browser's `EventSource` does that on network drop with its own
backoff. We surface the reconnect state via `state.reconnecting`
so the UI can show a "reconnecting…" pill (deferred to Spec 11's
mobile reconnect UX).

### I. Single task lane renderer — `apps/web/widgets/task-lane-card/`

```tsx
"use client";

import { useMissionStream } from "@/features/run-mission";
import { useT } from "@/shared/i18n";

import { TierBadge } from "./tier-badge";
import { ToolChip } from "./tool-chip";
import { ReasoningStream } from "./reasoning-stream";
import { ResultPreview } from "./result-preview";

export function TaskLaneCard({ missionId }: { missionId: string }) {
  const { events } = useMissionStream(missionId);
  const t = useT();

  // Project events into the three tiers
  const tokens = events.filter((e): e is Token => e.type === "token");
  const toolCalls = collapseToolCalls(events);
  const taskEnd = events.find((e): e is TaskEnd => e.type === "task_end");

  return (
    <div className="flex flex-col gap-3 p-4">
      <header className="flex items-center gap-2">
        <TierBadge tier={firstTier(events) ?? "http"} />
        <span className="font-mono text-[13px] truncate flex-1">
          {firstUrl(events) ?? t("mission", "loading")}
        </span>
      </header>

      <ReasoningStream tokens={tokens} />

      {toolCalls.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {toolCalls.map((c) => (
            <ToolChip key={c.id} call={c} />
          ))}
        </div>
      ) : null}

      {taskEnd ? <ResultPreview taskEnd={taskEnd} /> : null}
    </div>
  );
}
```

Sub-components:

- **`TierBadge`** — 22px tall pill with glyph + 2-letter code per
  `ui-context.md` (HT / ST / DY).
- **`ReasoningStream`** — receives tokens, batches every ~5 into a
  single render via `requestAnimationFrame`. Renders inside a
  `border-l-2 border-border/50 pl-3` block at
  `text-xs text-muted-foreground/70 leading-relaxed`.
- **`ToolChip`** — collapsed by default: dot + `tool_name` +
  `· 1.2s`. Click to expand and show args + summary.
- **`ResultPreview`** — `text-sm rounded-md border bg-card p-3`,
  shows `taskEnd.content.preview`. If the user expands it, shows
  the full `parsed_markdown` (fetched from `/api/missions/<id>`
  on demand).

### J. Command palette — `apps/web/widgets/command-palette/`

```tsx
"use client";

import { useEffect, useState } from "react";
import { Globe2, LogOut, Eye, PanelLeft, X } from "lucide-react";

import { Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandShortcut } from "@/components/ui/command";
import { useShortcut } from "@/shared/keyboard";
import { useT } from "@/shared/i18n";
import { useRecentMissions, useMissionStore } from "@/features/run-mission";
import { useClerk } from "@clerk/nextjs";

export function CommandPalette() {
  const t = useT();
  const [open, setOpen] = useState(false);
  const recent = useRecentMissions();
  const { openMission } = useMissionStore();
  const { signOut } = useClerk();

  useShortcut(["⌘k", "ctrl+k"], () => setOpen((v) => !v));

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder={t("common", "searchOrCommand")} />
      <CommandList>
        <CommandEmpty>{t("common", "nothingFound")}</CommandEmpty>

        {recent.length > 0 ? (
          <CommandGroup heading={t("common", "recent")}>
            {recent.map((m) => (
              <CommandItem
                key={m.id}
                onSelect={() => {
                  openMission(m.id);
                  setOpen(false);
                }}
              >
                <Globe2 className="h-3.5 w-3.5" />
                <span className="font-mono text-[13px] truncate">{m.url}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        ) : null}

        <CommandGroup heading={t("common", "actions")}>
          <CommandItem onSelect={() => focusUrlInput()}>
            <Globe2 className="h-3.5 w-3.5" />
            {t("mission", "newMission")}
            <CommandShortcut>⌘N</CommandShortcut>
          </CommandItem>
          <CommandItem onSelect={() => toggleReasoning()}>
            <Eye className="h-3.5 w-3.5" />
            {t("mission", "toggleReasoning")}
            <CommandShortcut>⌘.</CommandShortcut>
          </CommandItem>
          <CommandItem onSelect={() => toggleSidebar()}>
            <PanelLeft className="h-3.5 w-3.5" />
            {t("common", "toggleSidebar")}
            <CommandShortcut>⌘B</CommandShortcut>
          </CommandItem>
        </CommandGroup>

        <CommandGroup heading={t("common", "account")}>
          <CommandItem onSelect={() => void signOut()}>
            <LogOut className="h-3.5 w-3.5" />
            {t("common", "signOut")}
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
```

### K. Keyboard shortcut registry — `apps/web/shared/keyboard/`

A simple typed registry. One global `keydown` listener installs at
mount; handlers register by key combo + scope.

```tsx
"use client";

import { useEffect } from "react";

type KeyCombo = string | string[];
type Handler = (e: KeyboardEvent) => void;

const handlers = new Map<string, Handler>();

function normalize(combo: string): string {
  return combo
    .toLowerCase()
    .replace("⌘", "meta")
    .replace("ctrl", "control")
    .replace("⇧", "shift");
}

export function useShortcut(combo: KeyCombo, handler: Handler) {
  useEffect(() => {
    const combos = (Array.isArray(combo) ? combo : [combo]).map(normalize);
    const wrapped = (e: KeyboardEvent) => {
      const pressed = describe(e);
      if (combos.includes(pressed)) {
        e.preventDefault();
        handler(e);
      }
    };
    window.addEventListener("keydown", wrapped);
    return () => window.removeEventListener("keydown", wrapped);
  }, [combo, handler]);
}

function describe(e: KeyboardEvent): string {
  const parts = [
    e.metaKey ? "meta" : null,
    e.ctrlKey ? "control" : null,
    e.shiftKey ? "shift" : null,
    e.altKey ? "alt" : null,
    e.key.toLowerCase(),
  ].filter(Boolean);
  return parts.join("+");
}

export function KeyboardShortcuts() {
  // Mounted at the shell level; reserved for future global shortcuts
  // that don't have a natural home in a feature folder.
  return null;
}
```

### L. i18n keys

Add to `apps/web/shared/i18n/locales/en.ts` (or wherever the
existing per-namespace files live — Spec 08 doesn't change the
i18n architecture):

- `common.searchOrCommand` — "Search or run a command"
- `common.nothingFound` — "No matches"
- `common.recent` — "Recent"
- `common.actions` — "Actions"
- `common.account` — "Account"
- `common.toggleSidebar` — "Toggle sidebar"
- `common.signOut` — "Sign out"
- `common.goTo` — "Go to"
- `mission.urlPlaceholder` — "Paste a URL — ⌘↩ to run"
- `mission.yourMissions` — "Your missions"
- `mission.newMission` — "New URL mission"
- `mission.toggleReasoning` — "Toggle reasoning"
- `mission.loading` — "Loading…"
- `mission.noMissions` — "No missions yet"
- `mission.noMissionsHint` — "Paste a URL above or press {shortcut}"
- `mission.status_running` — "Running"
- `mission.status_pending` — "Queued"
- `mission.status_succeeded` — "Done"
- `mission.status_failed` — "Failed"
- `mission.status_cancelled` — "Cancelled"
- `validation.urlRequired` — "URL required"
- `validation.urlTooLong` — "URL too long"
- `validation.urlInvalid` — "URL invalid"
- `validation.missionFailed` — "Mission failed"

All sentence case, no exclamation marks, no marketing speak per
`ui-context.md` Voice & Copy.

### M. Order of operations

1. Tailwind 4 + shadcn `new-york` init (section A); add the 10
   shadcn components.
2. Bridge tokens in `app/globals.css`; override `--radius`.
3. Add `zustand`. Create `features/run-mission/store.ts`.
4. Build the keyboard registry in `shared/keyboard/`.
5. Build the BFF routes in `apps/web/app/api/missions/`.
6. Build the api side: introduce `POST /missions` (non-streaming
   start) and `GET /run-mission/<id>/stream` (attach by id) in
   `apps/api/app/routes.py`. Annotate the `asyncio.create_task`
   call with a `# TODO(spec-10): TaskGroup ownership` marker.
7. Build `useSubmitMission`, `useMissions`, `useMissionStream`,
   `useRecentMissions`.
8. Build the widgets in this order: `TopBar` → `MissionSidebar` →
   `MissionDetailSlideover` → `TaskLaneCard` (and its 4 sub-
   components) → `CommandPalette`.
9. Wire the shell at `(app)/layout.tsx` and replace
   `app/missions/page.tsx`.
10. Add i18n keys; remove any hardcoded strings the
    `i18n-keeper` agent flags.
11. Run the verification block.

## Out of Scope

- **Multi-lane stack** (N parallel task lanes) — Spec 11.
- **Mobile reconnect pill** UI / aggressive small-screen layout —
  Spec 11.
- **Full ARIA polite live region wiring** for streamed content —
  Spec 11 (single-lane in this spec is simple enough that the
  default text rendering is accessible).
- **URL discovery / description-mode form** — Spec 12.
- **Shareable mission URLs / search-param sync for the slide-over**
  — accepted limitation; revisit only if user explicitly asks.
- **Per-mission cost surfacing** — Spec 14.
- **Mission cancellation UI** — Spec 14 (Esc on the slide-over
  closes the slide-over only; cancellation comes later).
- **Snapshot retrieval / signed R2 URLs in the result preview** —
  Spec 14.
- **CI workflow** — separate spec after this; Spec 03's hooks are
  the primary gate today.

## Files

### Create

- `apps/web/components.json`
- `apps/web/components/ui/*` — generated by shadcn CLI: `button`,
  `input`, `dialog`, `sheet`, `command`, `kbd`, `separator`,
  `scroll-area`, `sidebar`, `tooltip`
- `apps/web/app/(app)/layout.tsx`
- `apps/web/app/(app)/missions/page.tsx`
- `apps/web/app/api/missions/route.ts`
- `apps/web/app/api/missions/[id]/route.ts`
- `apps/web/app/api/missions/[id]/stream/route.ts`
- `apps/web/widgets/top-bar/index.tsx`
- `apps/web/widgets/mission-sidebar/index.tsx`
- `apps/web/widgets/mission-sidebar/mission-row.tsx`
- `apps/web/widgets/mission-detail/index.tsx`
- `apps/web/widgets/task-lane-card/index.tsx`
- `apps/web/widgets/task-lane-card/tier-badge.tsx`
- `apps/web/widgets/task-lane-card/tool-chip.tsx`
- `apps/web/widgets/task-lane-card/reasoning-stream.tsx`
- `apps/web/widgets/task-lane-card/result-preview.tsx`
- `apps/web/widgets/command-palette/index.tsx`
- `apps/web/features/run-mission/use-submit-mission.ts`
- `apps/web/features/run-mission/use-missions.ts`
- `apps/web/features/run-mission/use-mission-stream.ts`
- `apps/web/features/run-mission/use-recent-missions.ts`
- `apps/web/features/run-mission/store.ts`
- `apps/web/features/run-mission/index.ts` (re-exports)
- `apps/web/entities/mission/types.ts`
- `apps/web/shared/keyboard/index.tsx`
- `apps/web/shared/utils/cn.ts`
- `apps/web/shared/i18n/keys/en.ts` — extend with the 24 new keys

### Edit

- `apps/web/app/globals.css` — bridge shadcn CSS variables to
  project tokens; set `--radius`
- `apps/web/app/layout.tsx` — keep `ClerkProvider`, no other
  changes
- `apps/web/app/missions/page.tsx` (placeholder from Spec 04) —
  **REPLACE** with the real `(app)/missions/page.tsx` (delete the
  old file as part of the move)
- `apps/web/package.json` — add `cmdk`, `zustand`, `lucide-react`
  if not added by shadcn
- `apps/api/app/routes.py` — add `POST /missions` (non-streaming
  start) and `GET /run-mission/<id>/stream` (attach by id) with
  the TaskGroup-deferred marker
- `apps/api/app/runner.py` — split `run_url_mission` into
  `start_url_mission` (creates rows, kicks off task) and
  `stream_existing_mission` (re-attaches via
  `emitter.stream(mission_id, last_event_id=...)`)

### Protected (do not touch)

- `apps/web/components/ui/*` — once generated by shadcn CLI, do
  not hand-edit. Re-run the CLI for updates. (These are added to
  `ai-workflow-rules.md`'s protected-files list — they already
  are; this spec just instantiates them.)
- All previous protected files (`apps/api/app/security.py`,
  past alembic migrations, generated SSE types).

## Verification

Run from the repo root.

- `pnpm install` resolves cleanly; `cmdk`, `zustand`, `lucide-react`
  exist in `apps/web/package.json`.
- `turbo run lint` exits 0 (Biome's `a11y` rules pass; no
  hardcoded strings flagged).
- `turbo run typecheck` exits 0 — strict TS passes; the
  `SseEvent` discriminated union from `@autumn/sse-protocol`
  resolves end-to-end through the hook into the renderers.
- `turbo run test` exits 0; new Vitest tests for the keyboard
  registry, `useMissionStream` (with a mock EventSource), and
  the URL validator.
- `turbo run build` exits 0.
- `turbo run dev` boots both apps. Sign in.
  - Land on `/missions`. Empty-state panel shows
    "No missions yet" + "Paste a URL above or press ⌘N" + the
    `<kbd>` chip.
  - Top bar shows the persistent URL input with autofocus on `/`.
  - `Cmd+K` opens the palette. Sections render: Recent (empty),
    Actions, Go to, Account.
  - Paste `https://example.com/`, press `Cmd+Enter`. The slide-
    over opens. Reasoning streams in dim text with the left
    border. A tool chip appears with a status dot and duration.
    On terminal, the result preview block fills with the parsed
    markdown excerpt.
  - Refresh the page; the mission appears in the sidebar under
    "Done"; clicking it re-opens the slide-over with the persisted
    state.
  - Open the slide-over for a `RUNNING` mission, kill the network
    momentarily; the UI's `state.reconnecting` flips and recovers.
- Lighthouse / axe pass: no critical accessibility violations on
  `/missions`.

Manual:

- `Esc` closes the slide-over and the palette.
- `/` focuses the URL input from anywhere.
- `Cmd+B` toggles the sidebar; the layout reflows without jank.
- The sign-in / sign-up pages from Spec 04 still work; their
  `(auth)` layout is untouched.
- The `fsd-architect` agent does not flag layer violations:
  no `entities/` imports from `features/`; no `features/` imports
  from sibling features; `'use client'` only on hook-using
  components.
- The `i18n-keeper` agent finds zero hardcoded English strings
  in any new `.tsx` file.
- The `react-doctor` skills (`next-best-practices`,
  `vercel-composition-patterns`, user-level `react-architecture`)
  raise no major findings.
- Visual: rows are 32px, status pills have leading dots,
  borders are two-tone, type scale matches `text-[13px]` /
  `text-xs` / `text-[11px]`, no element exceeds `h-9`.

## Done when

- [ ] Every Verification line passes.
- [ ] No invariant in `context/architecture.md` violated, with
  the exception of **invariant 3** (TaskGroup ownership), which
  this spec accepts as a temporary deviation: the
  `asyncio.create_task` call in `runner.py` carries a
  `# TODO(spec-10)` marker, is logged in `progress-tracker.md`'s
  Open Questions, and **must close in Spec 10**. The `scrape-
  pipeline-doctor` agent's review of Spec 10 fails until it does.
- [ ] `apps/api/app/security.py` was not edited.
- [ ] `apps/web/components/ui/*` was generated only via the
  shadcn CLI; no hand-edits.
- [ ] No hardcoded English strings in `apps/web/widgets/`,
  `apps/web/features/`, `apps/web/app/(app)/`.
- [ ] `context/progress-tracker.md` updated: Spec 08 to "Completed";
  Spec 09 to "In Progress"; the spec-10 invariant-3 deviation
  added to Open Questions.
- [ ] On a real Clerk dev instance with the api running, a
  10-second mission against `https://example.com/` renders end-
  to-end through the slide-over with three-tier visual hierarchy
  visibly distinct.
- [ ] `fsd-architect` agent run on `apps/web/**` finds zero
  layer violations.
- [ ] `i18n-keeper` agent run on `apps/web/**` finds zero
  hardcoded English strings.
- [ ] `code-reviewer` agent run on the chunk produces
  `CODE_REVIEW.md` with `Verdict: Approve`.
- [ ] `simplify` skill review on the diff returns no actionable
  findings.

## Scrape reliability note

This spec ships zero scraping behavior. Its contribution to
reliability is **observability for the user**: the streaming
hierarchy makes it obvious in real time which tier is running,
which tool just fired, how long it took, and what came back. A
silent failure becomes a visible failure (terminal `error` event
renders an inline error chip + retry hint), and a slow tier shows
its latency before the user wonders if anything is happening.

The user-facing reliability story is now: an authenticated user
can submit a URL, watch it run, see the result, refresh the page,
and find the mission persisted in the sidebar with its terminal
state. Every step is visible; nothing is silent. That visibility
is the reliability — failures that are visible get fixed; failures
that hide accumulate.
