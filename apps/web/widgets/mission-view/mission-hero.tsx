"use client";

import type { MissionRow } from "@/entities/mission/types";
import { CancelMissionButton } from "@/features/run-mission";
import { useT } from "@/shared/i18n";
import { cn } from "@/shared/utils/cn";

const _STATUS_PILL_CLASS = {
  pending: "bg-muted/40 text-muted-foreground",
  running: "bg-state-info/15 text-state-info",
  succeeded: "bg-state-success/15 text-state-success",
  failed: "bg-state-error/15 text-state-error",
  cancelled: "bg-muted/40 text-muted-foreground",
} as const;

/**
 * Hero band at the top of the mission detail view. Shows the prompt
 * (truncated at one line), a status pill, the mode badge, an
 * always-current elapsed counter (driven by mission timestamps so it
 * stays accurate across navigation), and the cancel button while the
 * mission is still in flight.
 *
 * Density-first composition: every value is on one line, fixed-height
 * (44px) so the band reads as a header without a content shift when
 * the prompt grows.
 */
export function MissionHero({
  mission,
  elapsedSeconds,
}: {
  mission: MissionRow | null;
  elapsedSeconds: number;
}) {
  const t = useT();
  if (!mission) {
    return <div className="h-11" aria-hidden />;
  }

  const prompt = _firstLine(mission.prompt);
  const isRunning = mission.status === "pending" || mission.status === "running";

  return (
    <div className="flex h-11 items-center gap-3 px-4">
      <span
        className={cn(
          "inline-flex h-5 items-center rounded-sm px-1.5 text-[11px] font-medium uppercase tracking-wide",
          _STATUS_PILL_CLASS[mission.status],
        )}
      >
        {t("mission", _statusKey(mission.status))}
      </span>
      <span className="font-mono text-[11px] uppercase tracking-wide text-muted-foreground/70">
        {mission.mode}
      </span>
      <span
        className="flex-1 truncate font-mono text-[13px] text-foreground"
        title={mission.prompt}
      >
        {prompt}
      </span>
      <time
        dateTime={`PT${elapsedSeconds}S`}
        className="font-mono text-[11px] tabular-nums text-muted-foreground"
      >
        <span className="sr-only">{t("mission", "elapsedAria", { seconds: elapsedSeconds })}</span>
        <span aria-hidden>{_formatElapsed(elapsedSeconds)}</span>
      </time>
      {isRunning ? <CancelMissionButton missionId={mission.id} /> : null}
    </div>
  );
}

function _firstLine(prompt: string): string {
  const line = prompt.split("\n", 1)[0]?.trim() ?? "";
  if (line.length <= 120) return line;
  return `${line.slice(0, 119)}…`;
}

function _formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function _statusKey(
  status: MissionRow["status"],
): "status_pending" | "status_running" | "status_succeeded" | "status_failed" | "status_cancelled" {
  return `status_${status}` as const;
}
