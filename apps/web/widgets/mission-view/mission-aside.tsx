"use client";

import type { MissionRow, TaskRow } from "@/entities/mission/types";
import { useT } from "@/shared/i18n";
import { cn } from "@/shared/utils/cn";

/**
 * Right-column metadata + summary stack for the master-detail mission
 * view. Splits density-first into three cards so the user can scan
 * mission-level numbers, the agent's natural-language summaries, and
 * the per-task latency/snapshot grid without horizontal scroll on a
 * 320px column.
 *
 * The summary card surfaces `tasks[].summary` — the one-paragraph string
 * the agent writes to `MissionResult.summary` when a task terminates
 * successfully. It is the "what was scraped" answer the user asked for;
 * absent for still-running missions and for tasks that did not reach a
 * successful completion.
 */
export function MissionAside({ mission }: { mission: MissionRow | null }) {
  const t = useT();
  if (!mission) {
    return <div className="hidden lg:block" aria-hidden />;
  }

  const tasks = mission.tasks ?? [];
  const succeeded = tasks.filter((task) => task.status === "succeeded");
  const failed = tasks.filter((task) => task.status === "failed");
  const cancelled = tasks.filter((task) => task.status === "cancelled");
  const summaries = tasks.filter((task) => task.summary && task.summary.trim().length > 0);
  const cost =
    mission.cost_cents > 0 ? `$${(mission.cost_cents / 100).toFixed(3)}` : t("mission", "costFree");

  return (
    <div className="flex flex-col gap-3 text-[12px]">
      <_Card title={t("mission", "asideOverview")}>
        <_Row label={t("mission", "asideMode")} value={mission.mode} mono />
        <_Row
          label={t("mission", "asideStatus")}
          value={t("mission", _statusKey(mission.status))}
        />
        <_Row label={t("mission", "asideCost")} value={cost} mono />
        <_Row
          label={t("mission", "asideTasks")}
          value={`${succeeded.length}/${tasks.length}`}
          mono
        />
        {failed.length > 0 ? (
          <_Row
            label={t("mission", "asideFailed")}
            value={String(failed.length)}
            valueClass="text-state-error"
            mono
          />
        ) : null}
        {cancelled.length > 0 ? (
          <_Row label={t("mission", "asideCancelled")} value={String(cancelled.length)} mono />
        ) : null}
        <_Row label={t("mission", "asideStarted")} value={_formatTime(mission.created_at)} mono />
        {mission.finished_at ? (
          <_Row
            label={t("mission", "asideFinished")}
            value={_formatTime(mission.finished_at)}
            mono
          />
        ) : null}
      </_Card>

      <_Card title={t("mission", "asideSummary")}>
        {summaries.length === 0 ? (
          <p className="text-muted-foreground">{t("mission", "asideSummaryEmpty")}</p>
        ) : (
          <ul className="flex flex-col gap-2.5">
            {summaries.map((task) => (
              <li key={task.id} className="flex flex-col gap-1">
                <span
                  className="truncate font-mono text-[11px] text-muted-foreground"
                  title={task.url}
                >
                  {_hostname(task.url)}
                </span>
                <p className="text-[12px] leading-relaxed text-foreground">{task.summary}</p>
              </li>
            ))}
          </ul>
        )}
      </_Card>

      {tasks.length > 0 ? (
        <_Card title={t("mission", "asideTaskList")}>
          <ul className="flex flex-col gap-1.5">
            {tasks.map((task) => (
              <_TaskRow key={task.id} task={task} />
            ))}
          </ul>
        </_Card>
      ) : null}
    </div>
  );
}

function _Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-md border border-border/50 bg-background/40">
      <header className="border-b border-border/40 px-3 py-1.5">
        <h3 className="font-mono text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          {title}
        </h3>
      </header>
      <div className="px-3 py-2">{children}</div>
    </section>
  );
}

function _Row({
  label,
  value,
  mono,
  valueClass,
}: {
  label: string;
  value: string;
  mono?: boolean;
  valueClass?: string;
}) {
  return (
    <div className="flex h-6 items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn(mono && "font-mono text-[11px] tabular-nums", valueClass)}>{value}</span>
    </div>
  );
}

const _TIER_LABEL: Record<TaskRow["tier_used"], string> = {
  http: "HT",
  stealth: "ST",
  dynamic: "DY",
};

const _STATUS_DOT: Record<TaskRow["status"], string> = {
  pending: "bg-muted-foreground/60",
  running: "bg-state-info",
  succeeded: "bg-state-success",
  failed: "bg-state-error",
  cancelled: "bg-muted-foreground/60",
};

function _TaskRow({ task }: { task: TaskRow }) {
  return (
    <li className="flex h-6 items-center gap-2">
      <span
        aria-hidden
        className={cn("h-1.5 w-1.5 shrink-0 rounded-full", _STATUS_DOT[task.status])}
      />
      <span className="w-7 shrink-0 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80">
        {_TIER_LABEL[task.tier_used]}
      </span>
      <span className="flex-1 truncate font-mono text-[11px] text-foreground/90" title={task.url}>
        {_hostname(task.url)}
      </span>
      {task.latency_ms != null ? (
        <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
          {_formatLatency(task.latency_ms)}
        </span>
      ) : null}
    </li>
  );
}

function _hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function _formatTime(iso: string): string {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  const d = new Date(ms);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function _formatLatency(ms: number): string {
  if (ms < 1_000) return `${ms}ms`;
  return `${(ms / 1_000).toFixed(1)}s`;
}

function _statusKey(
  status: MissionRow["status"],
): "status_pending" | "status_running" | "status_succeeded" | "status_failed" | "status_cancelled" {
  return `status_${status}` as const;
}
