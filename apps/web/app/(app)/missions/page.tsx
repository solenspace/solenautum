import { MissionDetailSlideover } from "@/widgets/mission-detail";
import { TaskLaneStack } from "@/widgets/task-lane-stack";

import { EmptyState } from "./empty-state";

/**
 * `/missions` — the only authenticated route. Owns the composition of the
 * slide-over body so the slide-over widget itself does not cross-import a
 * sibling widget (FSD rule). Spec 11 swaps the single-task `TaskLaneCard`
 * out for `TaskLaneStack`, the multi-lane renderer.
 */
export default function MissionsPage() {
  return (
    <>
      <EmptyState />
      <MissionDetailSlideover renderBody={(missionId) => <TaskLaneStack missionId={missionId} />} />
    </>
  );
}
