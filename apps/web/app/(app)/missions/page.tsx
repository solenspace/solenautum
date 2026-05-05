import { MissionDetailSlideover } from "@/widgets/mission-detail";
import { TaskLaneCard } from "@/widgets/task-lane-card";

import { EmptyState } from "./empty-state";

/**
 * `/missions` — the only authenticated route in Spec 08. Owns the
 * composition of the slide-over body so the slide-over widget itself does
 * not cross-import a sibling widget (FSD rule).
 */
export default function MissionsPage() {
  return (
    <>
      <EmptyState />
      <MissionDetailSlideover renderBody={(missionId) => <TaskLaneCard missionId={missionId} />} />
    </>
  );
}
