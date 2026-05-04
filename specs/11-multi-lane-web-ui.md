# 11 — multi-lane-web-ui

## Goal

Replace Spec 08's single `TaskLaneCard` with a stacked, collapsible
multi-lane renderer that handles the N-task missions Spec 10 emits.
After this spec, a 12-URL mission renders as 12 vertically stacked
lanes inside the slide-over, each with its own three-tier streaming
hierarchy. A sticky aggregate header tracks mission progress.
Keyboard navigation (J/K) auto-expands lanes on focus; Enter pins
expansion; X collapses. Successful lanes auto-collapse 1.5s after
terminal; failed and cancelled stay expanded. The mobile breakpoint
collapses to a swipeable single lane with a `2/12` counter. ARIA
live regions announce mission milestones only — never per-token,
never per-lane streaming.

## Dependencies

- `specs/06` — `SseEvent` typed discriminated union
- `specs/08` — slide-over shell, `useMissionStream`, command
  palette, keyboard registry, three-tier visual hierarchy
- `specs/09` — `error_code` events for `site_not_supported` etc.
  rendered as inline error chips
- `specs/10` — N-URL missions emit per-task `task_start` / `tool_*`
  / `task_end` events with `task_id`, plus mission-level
  `done` / `error`

## Design Decisions

Density posture and Linear / Vercel / Devin-v3 reference patterns
are the source of truth — research-backed directives below are
non-negotiable for this spec.

### Stack model

- **Vertical stack only.** No grid, no tabs, no accordion-with-
  closed-default. Lanes live in `flex flex-col gap-1.5`.
- **Auto-collapse rule**: a lane that emits `task_end` with
  status `succeeded` collapses 1.5s after the terminal event.
  `failed` and `cancelled` stay expanded so the user can read
  the error inline. Manual user expansion (`data-user-expanded`)
  overrides — never auto-collapse a lane the user pinned with
  Enter.
- **Lane order**: insertion order, by submission. The order in
  which the api emits `task_start` for each task. No re-sorting
  by status; users orient by position, not by completion.
- **DOM cost guard**: collapsed lane bodies use
  `content-visibility: auto; contain-intrinsic-size: 32px`. At
  N=20 with most lanes collapsed, the renderer pays for ~3-4
  expanded lanes worth of DOM.

### Aggregate header (sticky, above the stack)

- Four fields, in order: `{succeeded}/{total} done`,
  `{running} streaming`, `{failed} errored`, `{elapsed}` (mm:ss
  while running, total on terminal). All `font-mono tabular-nums`,
  `text-[11px]`, leading status dot per field.
- **Drop**: per-mission cost (lives in the sidebar / lane footer
  per Spec 14), estimated time remaining (LLM-based ETAs erode
  trust), per-tier breakdown.
- Reconnect chip (`Reconnecting…`) appears adjacent to the
  elapsed-time field when SSE drops; promoted to a banner if
  reconnection fails for >10s.
- `aria-live="polite"` region attached to the header announces
  milestone changes only: mission start, lane terminal,
  mission complete. Never per-token. Mission-level errors get
  `aria-live="assertive"` exactly once.

### Per-lane structure

Compact 32px row when collapsed; expanded body grows in place.

- Collapsed row (default after `succeeded`):
  `[status-dot] [tier-badge] [url-mono-truncated] [latency-mono] [chevron]`
- Expanded body adds:
  - **Reasoning** at `text-xs text-muted-foreground/70 leading-relaxed`
    inside `border-l-2 border-border/50 pl-3`. Three render modes
    determined by focus + idle state (see "Streaming density"
    below).
  - **Tool chips** row: `flex flex-wrap gap-1.5`. Each chip
    is `inline-flex h-6 items-center gap-1.5 rounded border
    border-border/50 bg-muted/40 px-1.5 text-[11px] font-mono`
    with a leading status dot. Click → inline expansion (not
    popover) with `transition-[height,opacity] duration-200`,
    showing args and response summary in a mono block bounded
    `max-h-32` with internal scroll.
  - **Result preview** at `text-sm text-foreground rounded-md
    border bg-card p-3` showing `task_end.content.preview`.
    On click, fetches full markdown from `/api/missions/<id>`.
  - **Inline error chip** (Spec 09 carry-over) when an `error`
    event with a known code lands before `task_end`.

### Streaming density (the wall-of-text problem)

- **Focused lane**: full reasoning stream, no truncation. Line-
  height comfortable. Per-token batched render every 60ms (5
  tokens per batch from Spec 08).
- **Unfocused lane, < 5s idle**: single-line tail showing the
  **last 80 characters** of reasoning, ellipsis-clipped via
  `data-[focused=false]:line-clamp-1`.
- **Unfocused lane, ≥ 5s idle**: collapse reasoning to a
  `…thinking` chip (mono, dim, 18px). Click or focus to
  re-expand; new tokens reset the idle timer.
- The "5s idle" timer resets on every incoming `token` event
  for the lane; per-lane state lives in `useTaskLanes`.

### Focus model and keyboard navigation

- `J` moves focus down, `K` moves focus up. Wraps at top/bottom.
- On focus, a collapsed lane **auto-expands** (the Linear "peek"
  pattern). When focus leaves and the lane wasn't pinned with
  Enter, the lane returns to its previous collapse state.
- `Enter` on a focused lane sets `data-user-expanded="true"`
  (pinned). The lane stays expanded regardless of focus or
  terminal status. `X` clears the pin and re-applies the
  default rule.
- `Esc` clears focus to the slide-over (lane focus → slide-over
  focus → close). Spec 08's `Esc closes slide-over` shortcut
  remains; the lane-focus version takes priority when a lane is
  focused.
- `⌘/` toggles reasoning visibility on the focused lane (per
  `ui-context.md` shortcuts table).
- Visual: focused lane gets
  `data-[focused=true]:border-l-2 data-[focused=true]:border-primary
   data-[focused=true]:bg-accent/30`. No full ring — too loud at
  density. The 2px left accent matches the reasoning-block left
  border for visual continuity.
- `Tab` cycles only within interactive elements *inside* the
  focused lane (chips, links). Lane-to-lane motion is J/K only.

### Mobile (< 768px)

- One lane visible at a time, full width. Swipe left/right
  (`react-swipeable` or a tiny custom touch handler) navigates.
- Sticky aggregate header gets a `{focused-index}/{total}`
  counter and a row of 4-color dots (one per lane, by status:
  green / amber / red / gray) so users know where the failing
  lanes are at a glance.
- The reasoning-text density rule still applies on mobile:
  unfocused-and-out-of-view lanes never render their full
  reasoning, even after focus animation.
- J/K shortcuts become swipe-left / swipe-right at this
  breakpoint.

### Empty / connecting / reconnect states

- **Empty (mission has no tasks yet)**: skeleton lanes — one
  per submitted URL, height-matched to the real row (`h-8`),
  `animate-pulse` on the inner content. Mission-level
  `Connecting…` chip in the aggregate header. Skeletons drop on
  a per-lane basis the moment that lane's first SSE event lands.
- **Reconnect**: `Reconnecting…` chip in the aggregate header
  next to the elapsed-time field. Spinner inside the chip;
  `text-[11px] text-muted-foreground`. After 10s of failed
  reconnect, promote to a full-width banner above the header
  with a `Retry` text-button.
- **Mission-level error** (`error` event with no `task_id`):
  red banner replaces the aggregate header; no lanes render.

### ARIA / accessibility

- One mission-level `aria-live="polite"` region on the slide-
  over root. Announcements:
  - Mission started: `t("mission","ariaMissionStarted",{count})`
  - Per-lane terminal: `t("mission","ariaLaneTerminal",
    {url, status})`
  - Mission complete: `t("mission","ariaMissionComplete",
    {succeeded, total})`
- Lane bodies set `role="log"` and `aria-live="off"` so screen-
  reader users navigate to a lane intentionally and read its
  contents on demand. Per-token announcements would be unusable
  at any N.
- Mission-level errors fire `aria-live="assertive"` exactly once
  with the full error message.
- Keyboard focus follows the visible focused lane via
  `aria-current="true"` on the focused lane row. Roving
  `tabindex` (focused lane = 0, others = -1) so Tab inside the
  lane stays within the lane's interactive children.

### What this spec does NOT do

- **Per-lane cancel (X to cancel a single lane)**: requires the
  cancellation endpoint, deferred to Spec 14. Spec 11 ships X
  as "clear pin" only. The cancellation enable comes when
  Spec 14 lands `DELETE /missions/{id}/tasks/{task_id}`.
- **Real cost surfacing in the aggregate header / lane footer**:
  Spec 14.
- **Snapshot retrieval (signed R2 URL on the result preview)**:
  Spec 14.

References:
- `context/ui-context.md` — full token table, Voice & Copy,
  shortcut table
- `context/architecture.md` — Storage Model (SSE ring buffer)
- `context/code-standards.md` — TypeScript, FSD layers
- Skills: `vercel-composition-patterns`, `next-best-practices`,
  user-level `react-architecture`
- Reference patterns: Linear issue rows, Devin v3 Sessions,
  Vercel deployment logs, LangSmith trace tree

## Implementation

### A. Restructure `apps/web/widgets/task-lane-card/` →
### `apps/web/widgets/task-lane-stack/`

Spec 08's `widgets/task-lane-card/` becomes
`widgets/task-lane-stack/` with these files:

```
apps/web/widgets/task-lane-stack/
├── index.tsx                  # TaskLaneStack — top-level
├── aggregate-header.tsx       # Sticky header with 4 fields + reconnect chip
├── task-lane-row.tsx          # One lane: collapsed row + expanded body
├── reasoning-stream.tsx       # Three-mode reasoning renderer
├── tool-chip.tsx              # Single tool chip with inline expansion
├── result-preview.tsx         # Result block with click-to-expand markdown
├── tier-badge.tsx             # (kept from Spec 08)
├── inline-error-chip.tsx      # (kept from Spec 09 carry-over)
├── lane-skeleton.tsx          # Skeleton lane for empty/connecting state
└── reconnect-chip.tsx         # Aggregate-header reconnect indicator
```

The old `task-lane-card/` directory is deleted in this spec.

### B. `TaskLaneStack` — top-level orchestrator

```tsx
"use client";

import { useEffect, useRef } from "react";

import { useMissionStream } from "@/features/run-mission";
import { useTaskLanes, useLaneFocus, useMissionSummary } from "@/features/run-mission";
import { useShortcut } from "@/shared/keyboard";

import { AggregateHeader } from "./aggregate-header";
import { TaskLaneRow } from "./task-lane-row";
import { LaneSkeleton } from "./lane-skeleton";
import { useT } from "@/shared/i18n";

export function TaskLaneStack({ missionId }: { missionId: string }) {
  const t = useT();
  const stream = useMissionStream(missionId);
  const lanes = useTaskLanes(missionId, stream.events);
  const summary = useMissionSummary(lanes, stream.isConnected, stream.reconnecting);
  const focus = useLaneFocus(lanes);

  useShortcut("j", () => focus.next());
  useShortcut("k", () => focus.previous());
  useShortcut("Enter", () => focus.pin());
  useShortcut("x", () => focus.unpin());

  const announceRef = useRef<HTMLDivElement>(null);
  // Milestone announcements only (see section H).

  if (lanes.length === 0) {
    return (
      <div className="flex flex-col gap-1.5 p-4">
        <AggregateHeader summary={summary} />
        {/* Skeleton lanes match the count of submitted URLs once known;
            until then, render a single connecting state. */}
        <ConnectingState />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5 p-4">
      <AggregateHeader summary={summary} />
      <div
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label={t("mission", "ariaMissionRegion")}
        ref={announceRef}
        className="sr-only"
      />
      <ul className="flex flex-col gap-1.5">
        {lanes.map((lane, index) => (
          <TaskLaneRow
            key={lane.taskId}
            lane={lane}
            isFocused={focus.index === index}
            onFocus={() => focus.setIndex(index)}
          />
        ))}
      </ul>
    </div>
  );
}
```

The `<ul>` role is implicit; `role="list"` not required when
flexbox is used per the WAI-ARIA practices (`<ul>` defaults to
list). `<li>` inside `TaskLaneRow` keeps the implicit semantics.

### C. `useTaskLanes` — events → per-lane projection

`apps/web/features/run-mission/use-task-lanes.ts`:

```tsx
import { useMemo } from "react";

import type { SseEvent, Tier } from "@autumn/sse-protocol";

export interface ToolCall {
  id: string;
  toolName: string;
  args?: Record<string, unknown>;
  durationMs?: number;
  ok?: boolean;
  summary?: string;
}

export interface TaskLane {
  taskId: string;
  url: string;
  tier: Tier;
  status: "pending" | "running" | "succeeded" | "failed" | "cancelled";
  reasoningTokens: string;
  toolCalls: ToolCall[];
  preview?: string;
  latencyMs?: number;
  errorCode?: string;
  errorMessage?: string;
  lastTokenAt: number;
  startedAt: number;
  finishedAt?: number;
}

export function useTaskLanes(missionId: string, events: SseEvent[]): TaskLane[] {
  return useMemo(() => {
    const byTaskId = new Map<string, TaskLane>();
    const order: string[] = [];

    for (const ev of events) {
      const taskId = "task_id" in ev && typeof ev.task_id === "string" ? ev.task_id : null;
      if (taskId == null) continue; // mission-level events handled in useMissionSummary

      let lane = byTaskId.get(taskId);
      if (!lane) {
        lane = {
          taskId,
          url: "",
          tier: "http",
          status: "pending",
          reasoningTokens: "",
          toolCalls: [],
          lastTokenAt: 0,
          startedAt: Date.now(),
        };
        byTaskId.set(taskId, lane);
        order.push(taskId);
      }

      switch (ev.type) {
        case "task_start":
          lane.url = ev.content.url;
          lane.tier = ev.content.tier;
          lane.status = "running";
          break;
        case "token":
          lane.reasoningTokens += ev.content;
          lane.lastTokenAt = Date.now();
          break;
        case "tool_start":
          lane.toolCalls.push({
            id: `${ev.seq}`,
            toolName: ev.content.tool_name,
            args: ev.content.args,
          });
          break;
        case "tool_end": {
          const lastIncomplete = [...lane.toolCalls].reverse().find((c) => c.ok == null);
          if (lastIncomplete) {
            lastIncomplete.durationMs = ev.content.duration_ms;
            lastIncomplete.ok = ev.content.ok;
            lastIncomplete.summary = ev.content.summary;
          }
          break;
        }
        case "task_end":
          lane.status = ev.content.status;
          lane.preview = ev.content.preview;
          lane.latencyMs = ev.content.latency_ms;
          lane.finishedAt = Date.now();
          break;
        case "error":
          if (taskId) {
            lane.errorCode = ev.content.code;
            lane.errorMessage = ev.content.message;
          }
          break;
      }
    }

    return order.map((id) => byTaskId.get(id)!);
  }, [events]);
}
```

The projection is pure and `useMemo`-cached — re-runs only when
`events` mutates. Spec 10's per-task SSE events with
monotonically increasing seq guarantee the order events arrive
matches the order this projection processes them.

### D. `useLaneFocus` — keyboard navigation state

`apps/web/features/run-mission/use-lane-focus.ts`:

```tsx
import { useCallback, useState } from "react";
import type { TaskLane } from "./use-task-lanes";


export interface LaneFocus {
  index: number;
  pinned: Set<string>;
  next: () => void;
  previous: () => void;
  setIndex: (i: number) => void;
  pin: () => void;
  unpin: () => void;
}


export function useLaneFocus(lanes: TaskLane[]): LaneFocus {
  const [index, setIndex] = useState(0);
  const [pinned, setPinned] = useState<Set<string>>(new Set());

  const next = useCallback(() => {
    setIndex((i) => (lanes.length === 0 ? 0 : (i + 1) % lanes.length));
  }, [lanes.length]);

  const previous = useCallback(() => {
    setIndex((i) => (lanes.length === 0 ? 0 : (i - 1 + lanes.length) % lanes.length));
  }, [lanes.length]);

  const pin = useCallback(() => {
    const lane = lanes[index];
    if (!lane) return;
    setPinned((prev) => new Set(prev).add(lane.taskId));
  }, [index, lanes]);

  const unpin = useCallback(() => {
    const lane = lanes[index];
    if (!lane) return;
    setPinned((prev) => {
      const next = new Set(prev);
      next.delete(lane.taskId);
      return next;
    });
  }, [index, lanes]);

  return { index, pinned, next, previous, setIndex, pin, unpin };
}
```

### E. `useMissionSummary` — aggregate-header state

`apps/web/features/run-mission/use-mission-summary.ts`:

```tsx
import { useEffect, useState } from "react";

import type { TaskLane } from "./use-task-lanes";


export interface MissionSummary {
  total: number;
  succeeded: number;
  running: number;
  failed: number;
  cancelled: number;
  elapsedMs: number;
  isConnected: boolean;
  reconnecting: boolean;
}


export function useMissionSummary(
  lanes: TaskLane[],
  isConnected: boolean,
  reconnecting: boolean,
): MissionSummary {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, []);

  const startedAt = lanes[0]?.startedAt ?? now;
  const allTerminal = lanes.every((l) => l.status !== "pending" && l.status !== "running");
  const stopAt = allTerminal
    ? Math.max(...lanes.map((l) => l.finishedAt ?? l.startedAt))
    : now;

  const total = lanes.length;
  const succeeded = lanes.filter((l) => l.status === "succeeded").length;
  const running = lanes.filter((l) => l.status === "running").length;
  const failed = lanes.filter((l) => l.status === "failed").length;
  const cancelled = lanes.filter((l) => l.status === "cancelled").length;

  return {
    total,
    succeeded,
    running,
    failed,
    cancelled,
    elapsedMs: Math.max(0, stopAt - startedAt),
    isConnected,
    reconnecting,
  };
}
```

### F. `AggregateHeader`

```tsx
"use client";

import { Loader2 } from "lucide-react";

import { useT } from "@/shared/i18n";
import type { MissionSummary } from "@/features/run-mission";

import { ReconnectChip } from "./reconnect-chip";


function fmt(ms: number) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}


export function AggregateHeader({ summary }: { summary: MissionSummary }) {
  const t = useT();
  return (
    <header className="sticky top-0 z-10 flex h-8 items-center gap-3 border-b border-border/50 bg-background/95 px-1 text-[11px] font-mono tabular-nums">
      <Field
        dot="bg-state-success"
        label={t("mission", "headerDone", { count: summary.succeeded })}
        value={`${summary.succeeded}/${summary.total}`}
      />
      <Field
        dot="bg-accent-primary"
        label={t("mission", "headerStreaming", { count: summary.running })}
        value={String(summary.running)}
      />
      <Field
        dot="bg-state-error"
        label={t("mission", "headerErrored", { count: summary.failed })}
        value={String(summary.failed)}
      />
      <Field dot="bg-text-muted" label={t("mission", "headerElapsed")} value={fmt(summary.elapsedMs)} />
      {summary.reconnecting ? <ReconnectChip /> : null}
    </header>
  );
}


function Field({ dot, label, value }: { dot: string; label: string; value: string }) {
  return (
    <span className="flex items-center gap-1.5 text-muted-foreground">
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden />
      <span className="text-foreground">{value}</span>
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground/70">{label}</span>
    </span>
  );
}
```

`headerDone` / `headerStreaming` / `headerErrored` use the i18n
plural API with `count`; the keys resolve to "done" /
"streaming" / "errored" in English.

### G. `TaskLaneRow` — collapsed + expanded states

```tsx
"use client";

import { useEffect, useRef } from "react";

import { ChevronDown } from "lucide-react";

import type { TaskLane } from "@/features/run-mission";
import { useT } from "@/shared/i18n";

import { TierBadge } from "./tier-badge";
import { ReasoningStream } from "./reasoning-stream";
import { ToolChip } from "./tool-chip";
import { ResultPreview } from "./result-preview";
import { InlineErrorChip } from "./inline-error-chip";


const AUTO_COLLAPSE_DELAY_MS = 1500;


export function TaskLaneRow({
  lane,
  isFocused,
  onFocus,
  isPinned,
}: {
  lane: TaskLane;
  isFocused: boolean;
  onFocus: () => void;
  isPinned: boolean;
}) {
  const t = useT();
  const ref = useRef<HTMLLIElement>(null);
  const hasError = !!lane.errorCode;
  const isTerminal = lane.status !== "pending" && lane.status !== "running";

  // Auto-collapse: succeeded lanes collapse 1.5s after terminal, unless pinned.
  const shouldAutoCollapse =
    !isPinned &&
    !isFocused &&
    lane.status === "succeeded" &&
    lane.finishedAt !== undefined &&
    Date.now() - lane.finishedAt > AUTO_COLLAPSE_DELAY_MS;

  // Expanded if focused, pinned, or any non-succeeded terminal, or running with no auto-collapse.
  const expanded = isFocused || isPinned || (isTerminal && lane.status !== "succeeded") || (!isTerminal) || !shouldAutoCollapse;

  // Scroll into view when focused.
  useEffect(() => {
    if (isFocused && ref.current) {
      ref.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [isFocused]);

  return (
    <li
      ref={ref}
      data-focused={isFocused}
      data-status={lane.status}
      data-user-expanded={isPinned}
      aria-current={isFocused || undefined}
      onClick={onFocus}
      className={[
        "rounded-md border border-border/50 bg-card",
        "data-[focused=true]:border-l-2 data-[focused=true]:border-primary data-[focused=true]:bg-accent/30",
        "transition-[height,opacity] duration-200 ease-out",
      ].join(" ")}
    >
      {/* Compact header row — always visible */}
      <div className="flex h-8 items-center gap-2 px-2 text-[13px]">
        <StatusDot status={lane.status} />
        <TierBadge tier={lane.tier} />
        <span className="flex-1 truncate font-mono text-[13px] text-foreground">
          {lane.url || t("mission", "loading")}
        </span>
        {lane.latencyMs != null ? (
          <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
            {(lane.latencyMs / 1000).toFixed(1)}s
          </span>
        ) : null}
        <ChevronDown
          className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${
            expanded ? "rotate-0" : "-rotate-90"
          }`}
          aria-hidden
        />
      </div>

      {/* Expanded body */}
      {expanded ? (
        <div
          className="flex flex-col gap-3 px-2 pb-3"
          style={{ contentVisibility: "auto", containIntrinsicSize: "200px" }}
          role="log"
          aria-live="off"
        >
          {hasError ? (
            <InlineErrorChip code={lane.errorCode!} message={lane.errorMessage} />
          ) : null}
          <ReasoningStream
            text={lane.reasoningTokens}
            isFocused={isFocused}
            lastTokenAt={lane.lastTokenAt}
          />
          {lane.toolCalls.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {lane.toolCalls.map((c) => (
                <ToolChip key={c.id} call={c} />
              ))}
            </div>
          ) : null}
          {lane.preview ? <ResultPreview preview={lane.preview} /> : null}
        </div>
      ) : null}
    </li>
  );
}


function StatusDot({ status }: { status: TaskLane["status"] }) {
  const cls = {
    pending: "bg-muted-foreground/40",
    running: "bg-accent-primary animate-pulse",
    succeeded: "bg-state-success",
    failed: "bg-state-error",
    cancelled: "bg-muted-foreground/60",
  }[status];
  return <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${cls}`} aria-hidden />;
}
```

The auto-collapse rule uses a derived `shouldAutoCollapse` value
checked on every render (the `Date.now()` comparison). To trigger
re-renders after the delay, the row subscribes to a 500ms timer
via `useMissionSummary`'s `now` state — the parent already
re-renders every 500ms during a running mission, which is enough
granularity for the 1.5s collapse delay.

### H. `ReasoningStream` — three-mode renderer

```tsx
"use client";

import { useEffect, useState } from "react";


const IDLE_THRESHOLD_MS = 5000;
const TAIL_CHARS = 80;


export function ReasoningStream({
  text,
  isFocused,
  lastTokenAt,
}: {
  text: string;
  isFocused: boolean;
  lastTokenAt: number;
}) {
  const [now, setNow] = useState(() => Date.now());
  const isIdle = now - lastTokenAt > IDLE_THRESHOLD_MS;

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  if (text.length === 0) return null;

  // Focused: full text, no truncation.
  if (isFocused) {
    return (
      <div className="border-l-2 border-border/50 pl-3 text-xs leading-relaxed text-muted-foreground/70">
        {text}
      </div>
    );
  }

  // Unfocused, idle: collapsed thinking chip.
  if (isIdle) {
    return (
      <span className="inline-flex h-5 items-center gap-1 rounded border border-border/50 bg-muted/40 px-1.5 text-[11px] font-mono text-muted-foreground">
        …thinking
      </span>
    );
  }

  // Unfocused, active: tail.
  const tail = text.slice(-TAIL_CHARS);
  return (
    <div className="border-l-2 border-border/50 pl-3 text-xs leading-relaxed text-muted-foreground/70 line-clamp-1">
      {tail}
    </div>
  );
}
```

### I. `ToolChip` — inline expansion

```tsx
"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";

import type { ToolCall } from "@/features/run-mission";


export function ToolChip({ call }: { call: ToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const dotCls =
    call.ok === true ? "bg-state-success" :
    call.ok === false ? "bg-state-error" :
    "bg-accent-primary animate-pulse";

  return (
    <div
      className="flex flex-col gap-1 transition-[height,opacity] duration-200"
      style={{ contentVisibility: "auto", containIntrinsicSize: "24px" }}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="inline-flex h-6 items-center gap-1.5 rounded border border-border/50 bg-muted/40 px-1.5 text-[11px] font-mono text-foreground hover:bg-muted/60"
      >
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotCls}`} aria-hidden />
        <span>{call.toolName}</span>
        {call.durationMs != null ? (
          <span className="text-muted-foreground tabular-nums">
            · {(call.durationMs / 1000).toFixed(1)}s
          </span>
        ) : null}
        <ChevronRight
          className={`h-3 w-3 text-muted-foreground transition-transform ${expanded ? "rotate-90" : ""}`}
          aria-hidden
        />
      </button>
      {expanded ? (
        <div className="max-h-32 overflow-auto rounded-md border border-border/50 bg-card p-2 font-mono text-[11px] leading-relaxed">
          {call.args ? <pre className="whitespace-pre-wrap">{JSON.stringify(call.args, null, 2)}</pre> : null}
          {call.summary ? <p className="mt-2 text-muted-foreground">{call.summary}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
```

### J. `ResultPreview`, `LaneSkeleton`, `ReconnectChip`,
### `InlineErrorChip` (carry-over)

Carry over Spec 08's `ResultPreview` and the Spec 09 `InlineErrorChip`
verbatim. Add two new files:

`lane-skeleton.tsx`:

```tsx
export function LaneSkeleton() {
  return (
    <li className="rounded-md border border-border/50 bg-card">
      <div className="flex h-8 items-center gap-2 px-2">
        <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/30 animate-pulse" />
        <span className="h-3 w-12 rounded bg-muted/40 animate-pulse" />
        <span className="flex-1 h-3 w-1/2 rounded bg-muted/40 animate-pulse" />
      </div>
    </li>
  );
}
```

`reconnect-chip.tsx`:

```tsx
"use client";

import { Loader2 } from "lucide-react";
import { useT } from "@/shared/i18n";


export function ReconnectChip() {
  const t = useT();
  return (
    <span className="inline-flex h-5 items-center gap-1 rounded border border-border/50 bg-muted/40 px-1.5 text-[11px] font-mono text-muted-foreground">
      <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
      {t("mission", "reconnecting")}
    </span>
  );
}
```

The "promote to banner after 10s" path is straightforward: a
hook in the slide-over watches `summary.reconnecting` with a
`useEffect` + `setTimeout`; on 10s elapsed without recovery,
swap the chip for a full-width `<div role="alert">` banner.
For Spec 11, ship the chip; ship the banner promotion only if a
mobile-network test fails the verification — otherwise it's
incremental and can land in Spec 15.

### K. Mobile (< 768px)

Implementation uses CSS media query + an `useMediaQuery` hook
(the standard shadcn pattern via `useEffect` + `matchMedia`).
At < 768px:

- The stack renders only `lanes[focusIndex]` full-width, with
  `aria-hidden="true"` on the others (still in the DOM for swipe
  cycling but not announced).
- `react-swipeable` (or a tiny custom `onTouchStart`/`onTouchEnd`
  handler) maps swipe-left → `focus.next()`, swipe-right →
  `focus.previous()`.
- The aggregate header shows `{focusIndex+1}/{total}` plus a row
  of small status dots — one per lane, color-coded by status
  (`succeeded` / `failed` / `running` / `cancelled` / `pending`).
- Reasoning streams use the focused-mode renderer for the visible
  lane only; tail and idle modes are not used on mobile because
  there is only ever one visible lane.

The mobile shortcut mapping is registered through the existing
keyboard-shortcut hook (`useShortcut`); J → `focus.next()` and K
→ `focus.previous()` work on mobile keyboards too.

Add `react-swipeable` to `apps/web/package.json`:

```bash
pnpm --filter @autumn/web add react-swipeable
```

### L. Mission-level milestone announcements

Inside `TaskLaneStack`:

```tsx
const announceRef = useRef<HTMLDivElement>(null);
const lastAnnouncedTerminalCount = useRef(0);

useEffect(() => {
  const terminalCount = lanes.filter(
    (l) => l.status === "succeeded" || l.status === "failed" || l.status === "cancelled",
  ).length;
  if (terminalCount > lastAnnouncedTerminalCount.current) {
    const newlyTerminal = lanes
      .slice(lastAnnouncedTerminalCount.current)
      .filter((l) => l.status !== "running" && l.status !== "pending");
    for (const lane of newlyTerminal) {
      if (announceRef.current) {
        announceRef.current.textContent = t("mission", "ariaLaneTerminal", {
          url: lane.url,
          status: lane.status,
        });
      }
    }
    lastAnnouncedTerminalCount.current = terminalCount;
  }
  if (terminalCount === lanes.length && lanes.length > 0) {
    announceRef.current!.textContent = t("mission", "ariaMissionComplete", {
      succeeded: lanes.filter((l) => l.status === "succeeded").length,
      total: lanes.length,
    });
  }
}, [lanes, t]);
```

The `aria-live="polite"` region ref lives in the live-region
`<div>` rendered by `TaskLaneStack` (section B). Announcements
overwrite each other (single live region); polite delivery means
the reader finishes its current sentence before the next
announcement.

### M. i18n keys (additions)

- `mission.headerDone` (with `count`; `_one` "done" / `_other`
  "done") — units stay singular in English; key kept plural-aware
  for future locales
- `mission.headerStreaming` — "streaming"
- `mission.headerErrored` — "errored"
- `mission.headerElapsed` — "elapsed"
- `mission.reconnecting` — "Reconnecting…"
- `mission.connecting` — "Connecting…"
- `mission.ariaMissionRegion` — "Mission status updates"
- `mission.ariaMissionStarted` — "Mission started with {count} URLs"
  (plural via count)
- `mission.ariaLaneTerminal` — "Lane {url} {status}"
- `mission.ariaMissionComplete` — "{succeeded} of {total} succeeded"
- `mission.ariaMissionFailed` — "Mission failed: {message}"

### N. Wire `MissionDetailSlideover` to use the stack

`apps/web/widgets/mission-detail/index.tsx`:

```tsx
import { TaskLaneStack } from "@/widgets/task-lane-stack";
// ... existing imports ...

export function MissionDetailSlideover() {
  // ... existing slide-over setup ...
  return (
    <Sheet ...>
      <SheetContent ...>
        <SheetHeader ...>
          {/* header content */}
        </SheetHeader>
        {openMissionId ? <TaskLaneStack missionId={openMissionId} /> : null}
      </SheetContent>
    </Sheet>
  );
}
```

The Spec 08 import of `TaskLaneCard` is replaced; the file is
deleted.

### O. Tests

- `apps/web/features/run-mission/use-task-lanes.test.ts` —
  given a sequence of SSE events for two tasks, asserts the
  projection produces two lanes with correctly attributed
  reasoning, tool calls, status, preview, errorCode.
- `apps/web/features/run-mission/use-lane-focus.test.ts` —
  J/K wraps; pin sets and persists; unpin clears; index resets to
  0 when lanes shrink.
- `apps/web/features/run-mission/use-mission-summary.test.ts` —
  counts update with status changes; elapsed clock ticks
  while running; freezes on terminal.
- `apps/web/widgets/task-lane-stack/task-lane-row.test.tsx` —
  collapsed by default after `succeeded` + 1.5s; stays expanded
  on `failed`; pin overrides; focus + auto-expand;
  `aria-current` flips with focus.
- `apps/web/widgets/task-lane-stack/reasoning-stream.test.tsx` —
  three modes verified: focused full text, unfocused tail (last
  80 chars), unfocused idle (`…thinking` chip).
- `apps/web/widgets/task-lane-stack/aggregate-header.test.tsx` —
  4 fields render with correct counts; reconnect chip appears
  when `reconnecting=true`.
- `apps/web/widgets/task-lane-stack/task-lane-stack.test.tsx` —
  end-to-end: feed a mock stream of 5 tasks; assert 5 lanes, J/K
  navigation works, milestone announcements fire on terminals.

All component tests use `I18nTestWrapper`. Radix dialog is mocked
in slide-over tests (Spec 08 pattern carries over).

### P. Order of operations

1. Delete `apps/web/widgets/task-lane-card/`. Move
   `tier-badge.tsx`, `result-preview.tsx`, `inline-error-chip.tsx`
   into `apps/web/widgets/task-lane-stack/`.
2. Add `react-swipeable` to web deps.
3. Build hooks: `useTaskLanes`, `useLaneFocus`,
   `useMissionSummary`. Their tests pass.
4. Build leaf widgets: `ReasoningStream`, `ToolChip`,
   `LaneSkeleton`, `ReconnectChip`, `AggregateHeader`,
   `TaskLaneRow`. Their tests pass.
5. Build `TaskLaneStack` orchestrator.
6. Wire `MissionDetailSlideover` to render the stack.
7. Implement mobile breakpoint behavior (single-lane visible +
   swipe).
8. Add the 11 i18n keys.
9. Run the verification block.

## Out of Scope

- **Per-lane cancel (X to cancel one task)** — Spec 14.
- **Real cost surfacing** — Spec 14.
- **Snapshot retrieval URL on result preview** — Spec 14.
- **Reconnect-banner promotion at 10s** — Spec 15 (hardening), or
  earlier if a mobile-network test fails verification.
- **`selector_recovered` event rendering** — Spec 13 ships the
  events; Spec 13 also wires their UI surfacing on the lane
  (small "selectors recovered N times" indicator inline near the
  tool chips).
- **URL discovery surface (description-mode form, URL approval
  gate)** — Spec 12. The description-mode mission still renders
  through `TaskLaneStack` once tasks start; the discovery UI is
  pre-task.

## Files

### Create

- `apps/web/widgets/task-lane-stack/index.tsx`
- `apps/web/widgets/task-lane-stack/aggregate-header.tsx`
- `apps/web/widgets/task-lane-stack/task-lane-row.tsx`
- `apps/web/widgets/task-lane-stack/reasoning-stream.tsx`
- `apps/web/widgets/task-lane-stack/tool-chip.tsx`
- `apps/web/widgets/task-lane-stack/lane-skeleton.tsx`
- `apps/web/widgets/task-lane-stack/reconnect-chip.tsx`
- `apps/web/features/run-mission/use-task-lanes.ts`
- `apps/web/features/run-mission/use-lane-focus.ts`
- `apps/web/features/run-mission/use-mission-summary.ts`
- The seven test files listed in section O

### Edit

- `apps/web/widgets/mission-detail/index.tsx` — render
  `TaskLaneStack` instead of `TaskLaneCard`
- `apps/web/features/run-mission/index.ts` — re-export the new
  hooks
- `apps/web/shared/i18n/keys/en.ts` — append 11 new keys
- `apps/web/package.json` — add `react-swipeable`
- `apps/web/widgets/task-lane-card/` — **DELETE** the directory;
  the surviving children (`tier-badge`, `result-preview`,
  `inline-error-chip`) move into the new `task-lane-stack/`
  directory

### Protected (do not touch)

- `apps/web/components/ui/*`
- `apps/api/app/security.py`
- `packages/sse-protocol/generated/**`
- All previous protected files

## Verification

Run from the repo root.

- `pnpm install` resolves `react-swipeable` cleanly.
- `turbo run lint` exits 0 (Biome's `a11y` rules pass against
  the new components; no hardcoded English strings flagged).
- `turbo run typecheck` exits 0 — strict TS passes; the
  generated `SseEvent` discriminated union narrows correctly
  inside the projection in `useTaskLanes`.
- `turbo run test` exits 0; all seven new test files pass.
- `turbo run build` exits 0.
- `git ls-files apps/web/widgets/task-lane-card` returns nothing
  (directory deleted).

Manual:

- `turbo run dev` boots both apps. Submit a 5-URL mission via
  Cmd+Shift+N. Slide-over opens.
  - Aggregate header shows `0/5 done · 0 streaming · 0 errored ·
    00:00`.
  - All 5 skeleton lanes render immediately.
  - As tasks emit `task_start`, skeletons swap to real lanes
    one-by-one in submission order.
  - Streaming reasoning shows last 80 chars on unfocused lanes.
  - Press J — focus moves to lane 2, auto-expands, full
    reasoning visible.
  - Press Enter on lane 2 — pin engaged. Press K back to lane 1
    — lane 2 stays expanded.
  - Press X on the focused lane — pin clears.
  - Lane 3 succeeds — auto-collapses 1.5s later.
  - Lane 4 fails (e.g., Akamai-fronted URL) — stays expanded
    with the inline error chip.
  - Aggregate counts update: `1/5 done · 3 streaming · 1 errored`.
  - Mission terminal: `done` event fires; aggregate shows
    `4/5 done · 0 streaming · 1 errored`.
- Forced disconnect mid-mission → reconnect chip appears in the
  aggregate header; clears on reconnect.
- `Cmd+/` toggles reasoning visibility on the focused lane.
- Resize viewport to 375px (mobile). Stack collapses to single
  lane visible; swipe left/right cycles. Status-dot row in the
  aggregate header reflects all 5 lanes; failing lane has a red
  dot.
- Open Chrome devtools accessibility tree → confirm one
  `aria-live="polite"` region on the slide-over root; per-lane
  bodies have `role="log" aria-live="off"`. No assertive
  announcements during streaming.
- Lighthouse / axe on `/missions` with the slide-over open: no
  critical accessibility violations. Color-contrast checks pass
  for tier badges (the glyph + 2-letter code from `ui-context.md`
  satisfies color-blind safety).

## Done when

- [ ] Every Verification line passes.
- [ ] No invariant in `context/architecture.md` violated.
- [ ] No `console.log` calls remain in any new file (Biome
  `noConsole` rule from Spec 02 enforces this).
- [ ] No hardcoded English strings; `i18n-keeper` agent
  flags zero violations.
- [ ] `fsd-architect` agent flags zero layer violations:
  `widgets/task-lane-stack/` does not import from
  `app/`, `widgets/` does not import from `widgets/` siblings
  except through composition.
- [ ] On a real Clerk dev instance, a 12-URL mission renders
  end-to-end with all the verification points above.
- [ ] `apps/web/components/ui/*` was not edited.
- [ ] `context/progress-tracker.md` updated: Spec 11 to
  "Completed"; Spec 12 to "In Progress"; Current Goal updated.
- [ ] `fsd-architect` agent run on `apps/web/**` finds zero
  layer violations.
- [ ] `i18n-keeper` agent run on `apps/web/**` finds zero
  hardcoded English strings.
- [ ] `code-reviewer` agent run on the chunk produces
  `CODE_REVIEW.md` with `Verdict: Approve`.
- [ ] `simplify` skill review on the diff returns no actionable
  findings.

## Scrape reliability note

This spec ships zero scraping behavior. Its reliability
contribution is **operator awareness**: at N=12 concurrent
tasks, the operator can tell at a glance which tasks are
running, which succeeded, which failed, and why. The aggregate
header gives a per-mission glance; lane status dots give per-
task glance; J/K + auto-expand let the operator drill into any
failing lane in two keystrokes; the inline error chip with a
named code (`site_not_supported`, `not_found`,
`render_timeout`, `upstream_error`) tells them what to try
next.

The 5s-idle reasoning collapse is the single biggest cognitive-
load reduction in this build — without it, 12 simultaneously
streaming reasoning blocks become unreadable noise within
seconds. The pattern matches Devin v3's "collapsed thought"
solution to the same problem.

What remains: per-lane cancel + real cost surface (Spec 14),
URL-discovery flow (Spec 12), adaptive selectors (Spec 13),
hardening (Spec 15).
