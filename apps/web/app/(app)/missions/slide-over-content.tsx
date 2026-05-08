"use client";

import { useMemo } from "react";

import {
  useDiscoveredUrls,
  useMissionDetail,
  useMissionPhase,
  useMissionStore,
  useMissionStream,
} from "@/features/run-mission";
import { useT } from "@/shared/i18n";
import { ApprovalGate } from "@/widgets/approval-gate";
import { DiscoveredList } from "@/widgets/approval-gate/discovered-list";
import { DiscoveryHeader } from "@/widgets/approval-gate/discovery-header";
import { TaskLaneStack } from "@/widgets/task-lane-stack";

/**
 * Phase-driven slide-over body. The mission's phase is derived from the
 * SSE event stream and selects which child block to render:
 *
 *   * `discovering` — streaming list of `DiscoveredUrl`s with a pulsing
 *     header (rows append as `url_discovered` events arrive).
 *   * `awaiting_approval` — the approval gate (checkboxes, inline edit,
 *     bulk toolbar). Submit POSTs `/api/missions/{id}/approve`.
 *   * `scraping` / `done` — the multi-lane task stack (Spec 11).
 *   * `null` — connecting placeholder shown until the first event lands.
 *
 * Lives at the page layer because composition crosses widget boundaries
 * (FSD: widgets cannot import sibling widgets); the page is the single
 * place that knows how the mission detail body is assembled.
 */
export function SlideOverContent() {
  const t = useT();
  const missionId = useMissionStore((s) => s.openMissionId);
  // Hooks must run unconditionally — pass an empty id when no mission is
  // open; the wrapping `MissionDetailSlideover` only renders this body
  // when `openMissionId` is non-null, so the empty branch never paints.
  const stream = useMissionStream(missionId ?? "");
  const detail = useMissionDetail(missionId);

  // Hydration baseline: the api's per-mission SSE ring buffer evicts
  // 60s after a mission terminates, so reattaching to a finished
  // mission would otherwise stay on "Connecting…" forever. The detail
  // fetch returns the persisted task list; we synthesize SSE events
  // from it and merge with the live stream so the lane stack reads from
  // a single events array. Live deltas (newer `seq`) take precedence.
  const mergedEvents = useMemo(() => {
    if (stream.events.length === 0) return detail.syntheticEvents;
    if (detail.syntheticEvents.length === 0) return stream.events;
    const seen = new Set(stream.events.map((e) => `${e.task_id ?? "_"}:${e.type}`));
    const baseline = detail.syntheticEvents.filter(
      (e) => !seen.has(`${e.task_id ?? "_"}:${e.type}`),
    );
    return [...baseline, ...stream.events];
  }, [stream.events, detail.syntheticEvents]);

  const mergedStream = useMemo(() => ({ ...stream, events: mergedEvents }), [stream, mergedEvents]);

  const phase = useMissionPhase(mergedEvents);
  const discovered = useDiscoveredUrls(mergedEvents);

  if (!missionId) return null;

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

  // Render the lane stack as soon as we have ANY task data (from SSE OR
  // hydration), even before the phase derivation has fired. For a
  // terminal mission the synthesized events already include the
  // mission-level `done`, so phase derives correctly on first paint.
  if (phase === "scraping" || phase === "done" || detail.mission?.tasks?.length) {
    return <TaskLaneStack missionId={missionId} stream={mergedStream} />;
  }

  return (
    <div className="flex h-full items-center justify-center px-6 text-[11px] text-muted-foreground">
      {t("mission", "connecting")}
    </div>
  );
}
