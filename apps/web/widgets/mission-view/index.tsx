"use client";

import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

import {
  type MissionStreamState,
  useDiscoveredUrls,
  useMissionDetail,
  useMissionPhase,
  useMissionStream,
} from "@/features/run-mission";
import { useT } from "@/shared/i18n";
import { cn } from "@/shared/utils/cn";
import { ApprovalGate } from "@/widgets/approval-gate";
import { DiscoveredList } from "@/widgets/approval-gate/discovered-list";
import { DiscoveryHeader } from "@/widgets/approval-gate/discovery-header";
import { TaskLaneStack } from "@/widgets/task-lane-stack";

import { MissionAside } from "./mission-aside";
import { MissionHero } from "./mission-hero";

/**
 * Master-detail mission view. Replaces the prior slide-over pattern,
 * which collapsed every mission into a 384–896px panel that lost its
 * state on close and starved the main pane of useful content.
 *
 * Layout (≥ lg): hero band along the top + two-column body where the
 * left column owns the live transcript (phase-aware: discovery /
 * approval / task lanes) and the right column owns the metadata aside
 * (summary, timestamps, mode, cost, snapshot count). Below `lg` the
 * aside stacks above the lanes so the same content reads as one
 * vertical column on tablet / phone, no horizontal scroll.
 *
 * State survives across navigation: the route is the source of truth.
 * `useMissionDetail` rehydrates the persisted task list on mount, so
 * leaving and coming back lands on the same content (instead of a
 * "Connecting…" placeholder a la the previous slide-over).
 */
export function MissionView({ missionId }: { missionId: string }) {
  const t = useT();
  const stream = useMissionStream(missionId);
  const detail = useMissionDetail(missionId);

  // Wall-clock elapsed counter — derived from `mission.created_at` and
  // `mission.finished_at`, NOT from the SSE event sequence. Reopening
  // an old mission would otherwise read "00:00 elapsed" because the
  // synthesized events have no timestamps. Re-renders once a second
  // while the mission is still running; for terminal missions the
  // value is computed once and frozen.
  const elapsedSeconds = useElapsedSeconds(detail.mission);

  const isHydratedTerminal =
    detail.mission?.status === "succeeded" ||
    detail.mission?.status === "failed" ||
    detail.mission?.status === "cancelled";

  // The detail fetch is one-shot per missionId; without this nudge the
  // metadata aside (Status / Cost / Tasks / per-task `summary`) stays
  // on the in-flight snapshot after the mission terminates over SSE.
  // Watch the live stream for a mission-level `done` and refetch once.
  const sawLiveDone = stream.events.some((e) => e.type === "done" && e.task_id === null);
  const { refetch } = detail;
  useEffect(() => {
    if (sawLiveDone && !isHydratedTerminal) refetch();
  }, [sawLiveDone, isHydratedTerminal, refetch]);

  const mergedEvents = useMemo(() => {
    const filtered = isHydratedTerminal
      ? stream.events.filter(
          (e) =>
            !(
              e.type === "error" &&
              e.task_id === null &&
              (e as unknown as { content?: { code?: string } }).content?.code === "resume_lost"
            ),
        )
      : stream.events;
    if (filtered.length === 0) return detail.syntheticEvents;
    if (detail.syntheticEvents.length === 0) return filtered;
    const seen = new Set(filtered.map((e) => `${e.task_id ?? "_"}:${e.type}`));
    const baseline = detail.syntheticEvents.filter(
      (e) => !seen.has(`${e.task_id ?? "_"}:${e.type}`),
    );
    return [...baseline, ...filtered];
  }, [stream.events, detail.syntheticEvents, isHydratedTerminal]);

  const mergedStream: MissionStreamState = useMemo(
    () => ({
      ...stream,
      events: mergedEvents,
      reconnecting: isHydratedTerminal ? false : stream.reconnecting,
      isConnected: isHydratedTerminal ? true : stream.isConnected,
    }),
    [stream, mergedEvents, isHydratedTerminal],
  );

  const phase = useMissionPhase(mergedEvents);
  const discovered = useDiscoveredUrls(mergedEvents);

  if (detail.isLoading && !detail.mission) {
    return <MissionViewShell hero={null} aside={null} />;
  }

  if (!detail.mission && detail.error) {
    return (
      <MissionViewShell
        hero={null}
        aside={null}
        body={
          <div
            role="alert"
            className="rounded-md border border-state-error/40 bg-state-error/5 px-3 py-2 text-[12px] text-state-error"
          >
            {t("mission", "missionDetailFetchFailed")}
          </div>
        }
      />
    );
  }

  return (
    <MissionViewShell
      hero={<MissionHero mission={detail.mission} elapsedSeconds={elapsedSeconds} />}
      aside={<MissionAside mission={detail.mission} />}
      body={renderBody({ phase, discovered, missionId, stream: mergedStream })}
    />
  );
}

interface RenderBodyArgs {
  phase: ReturnType<typeof useMissionPhase>;
  discovered: ReturnType<typeof useDiscoveredUrls>;
  missionId: string;
  stream: MissionStreamState;
}

function renderBody({ phase, discovered, missionId, stream }: RenderBodyArgs): ReactNode {
  if (phase === "discovering") {
    return (
      <div className="flex flex-col">
        <DiscoveryHeader count={discovered.length} streaming />
        <DiscoveredList urls={discovered} />
      </div>
    );
  }
  if (phase === "awaiting_approval") {
    return (
      <div className="flex flex-col">
        <DiscoveryHeader count={discovered.length} streaming={false} />
        <ApprovalGate missionId={missionId} discoveredUrls={discovered} />
      </div>
    );
  }
  return <TaskLaneStack missionId={missionId} stream={stream} />;
}

interface ShellProps {
  hero: ReactNode;
  aside: ReactNode;
  body?: ReactNode;
}

function MissionViewShell({ hero, aside, body }: ShellProps) {
  return (
    <div className="flex h-full flex-col">
      <div className={cn("border-b border-border/50 bg-background/80")}>{hero}</div>
      <div className="grid flex-1 grid-cols-1 gap-6 overflow-auto p-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">{body}</div>
        <aside className="lg:sticky lg:top-4 lg:self-start">{aside}</aside>
      </div>
    </div>
  );
}

function useElapsedSeconds(mission: { created_at: string; finished_at: string | null } | null) {
  const [tick, setTick] = useState(0);
  const finished = mission?.finished_at != null;

  useEffect(() => {
    if (!mission || finished) return;
    const id = window.setInterval(() => setTick((n) => n + 1), 1_000);
    return () => window.clearInterval(id);
  }, [mission, finished]);

  if (!mission) return 0;
  const start = Date.parse(mission.created_at);
  if (Number.isNaN(start)) return 0;
  const end = mission.finished_at ? Date.parse(mission.finished_at) : Date.now() + tick * 0;
  return Math.max(0, Math.round((end - start) / 1000));
}
