import { MissionDetailSlideover } from "@/widgets/mission-detail";

import { EmptyState } from "./empty-state";
import { SlideOverContent } from "./slide-over-content";

/**
 * `/missions` — the only authenticated route. Owns the composition of the
 * slide-over body so the slide-over widget itself does not cross-import a
 * sibling widget (FSD rule). Spec 11 swapped the single-task `TaskLaneCard`
 * for `TaskLaneStack`; Spec 12 wraps the body in a phase-driven state
 * machine that selects between discovery list, approval gate, and task
 * lanes.
 */
export default function MissionsPage() {
  return (
    <>
      <EmptyState />
      <MissionDetailSlideover
        renderBody={(missionId) => <SlideOverContent missionId={missionId} />}
      />
    </>
  );
}
