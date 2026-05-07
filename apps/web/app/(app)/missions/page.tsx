import { CancelMissionButton } from "@/features/run-mission";
import { MissionDetailSlideover } from "@/widgets/mission-detail";

import { EmptyState } from "./empty-state";
import { SlideOverContent } from "./slide-over-content";

export default function MissionsPage() {
  return (
    <>
      <EmptyState />
      <MissionDetailSlideover body={<SlideOverContent />} headerAction={<CancelMissionButton />} />
    </>
  );
}
