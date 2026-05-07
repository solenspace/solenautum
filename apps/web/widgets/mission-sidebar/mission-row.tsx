"use client";

import type { MissionRow as MissionRowData, MissionStatus } from "@/entities/mission/types";
import { useMissionStore } from "@/features/run-mission";
import { cn } from "@/shared/utils/cn";

/** Status → dot color, mapped to project tokens (see `globals.css`). */
const _DOT_COLOR: Record<MissionStatus, string> = {
  pending: "bg-muted-foreground/60",
  running: "bg-primary",
  succeeded: "bg-state-success",
  failed: "bg-state-error",
  cancelled: "bg-muted-foreground/60",
};

function _shortId(id: string): string {
  return id.slice(0, 8);
}

function _relativeTime(iso: string): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "—";
  const diffMs = Date.now() - then;
  const seconds = Math.round(diffMs / 1_000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.round(hours / 24);
  return `${days}d`;
}

/**
 * Cost cell content (Spec 14):
 * - `cost_cents > 0` — render `$X.XXX`.
 * - `cost_cents === 0` on a terminal mission — render `?` to signal that
 *   the Langfuse fetch failed or the mission genuinely had no LLM
 *   spend. The column is `NOT NULL DEFAULT 0` on the api side so we
 *   cannot distinguish "unknown" from "free" without an extra sentinel;
 *   `?` covers both for users who care about cost.
 * - Pre-terminal — render empty (cost only lands at the `done` event).
 */
function _formatCost(mission: MissionRowData): string {
  if (mission.cost_cents > 0) {
    return `$${(mission.cost_cents / 100).toFixed(3)}`;
  }
  if (mission.status === "succeeded" || mission.status === "failed") {
    return "?";
  }
  return "";
}

export function MissionRow({ mission }: { mission: MissionRowData }) {
  const open = useMissionStore((s) => s.openMission);
  const cost = _formatCost(mission);
  return (
    <button
      type="button"
      onClick={() => open(mission.id)}
      className="group flex h-8 w-full items-center gap-2 rounded-md px-3 text-left transition-colors hover:bg-accent/40 data-[state=open]:bg-accent/40"
    >
      <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", _DOT_COLOR[mission.status])} />
      <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
        {_shortId(mission.id)}
      </span>
      <span className="flex-1 truncate font-mono text-[13px] text-foreground">
        {mission.prompt}
      </span>
      {cost ? (
        <span className="font-mono text-[11px] text-muted-foreground/70 tabular-nums">{cost}</span>
      ) : null}
      <span className="font-mono text-[11px] text-muted-foreground/70 tabular-nums">
        {_relativeTime(mission.created_at)}
      </span>
    </button>
  );
}
