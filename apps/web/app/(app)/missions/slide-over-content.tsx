"use client";

import { useDiscoveredUrls, useMissionPhase, useMissionStream } from "@/features/run-mission";
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
export function SlideOverContent({ missionId }: { missionId: string }) {
  const t = useT();
  const stream = useMissionStream(missionId);
  const phase = useMissionPhase(stream.events);
  const discovered = useDiscoveredUrls(stream.events);

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

  if (phase === "scraping" || phase === "done") {
    return <TaskLaneStack missionId={missionId} />;
  }

  return (
    <div className="flex h-full items-center justify-center px-6 text-[11px] text-muted-foreground">
      {t("mission", "connecting")}
    </div>
  );
}
