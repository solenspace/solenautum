"use client";

import type { MissionSummary } from "@/features/run-mission";
import { useT } from "@/shared/i18n";
import { cn } from "@/shared/utils/cn";

import { ReconnectChip } from "./reconnect-chip";

/**
 * Sticky four-field mission header. Numbers stay
 * `font-mono tabular-nums` so a digit change doesn't shift the layout.
 * The reconnect chip slides in next to the elapsed-time field while
 * `summary.reconnecting` is true.
 */
export function AggregateHeader({ summary }: { summary: MissionSummary }) {
  const t = useT();
  return (
    <header className="sticky top-0 z-10 flex h-8 items-center gap-3 border-b border-border/50 bg-background/95 px-1 font-mono text-[11px] tabular-nums">
      <Field
        dot="bg-state-success"
        label={t("mission", "headerDone", { count: summary.succeeded })}
        value={`${summary.succeeded}/${summary.total}`}
      />
      <Field
        dot="bg-primary"
        label={t("mission", "headerStreaming")}
        value={String(summary.running)}
      />
      <Field
        dot="bg-state-error"
        label={t("mission", "headerErrored")}
        value={String(summary.failed)}
      />
      <Field
        dot="bg-muted-foreground"
        label={t("mission", "headerElapsed")}
        value={_fmtElapsed(summary.elapsedMs)}
      />
      {summary.reconnecting ? <ReconnectChip /> : null}
    </header>
  );
}

function Field({ dot, label, value }: { dot: string; label: string; value: string }) {
  return (
    <span className="flex items-center gap-1.5 text-muted-foreground">
      <span className={cn("h-1.5 w-1.5 rounded-full", dot)} aria-hidden />
      <span className="text-foreground">{value}</span>
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground/70">{label}</span>
    </span>
  );
}

function _fmtElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}
