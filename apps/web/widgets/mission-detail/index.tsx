"use client";

import type { ReactNode } from "react";

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMissionStore } from "@/features/run-mission";

/**
 * Right-side slide-over for the open mission. URLs are not synced to query
 * params in Spec 08 (no shareable links — accepted MVP tradeoff). The
 * `Sheet` primitive (Base UI Dialog under the hood) handles `Esc`-to-close
 * and outside-click-to-close out of the box.
 *
 * `renderBody` and the optional `renderHeaderAction` are render-prop slots
 * so this widget remains composition-only — it does not import sibling
 * widgets or features, preserving FSD's no-cross-feature rule. Spec 14's
 * `Cancel mission` text-button is composed in the page layer and passed
 * through `renderHeaderAction`.
 */
export interface MissionDetailSlideoverProps {
  /** Renders inside the sheet body. Receives the open mission id; called
   * only while a mission is open so the consumer never has to null-check. */
  renderBody: (missionId: string) => ReactNode;
  /** Optional header action slot — receives the open mission id, renders
   * to the right of the title. Used for the Spec 14 cancel button. */
  renderHeaderAction?: (missionId: string) => ReactNode;
}

export function MissionDetailSlideover({
  renderBody,
  renderHeaderAction,
}: MissionDetailSlideoverProps) {
  const openMissionId = useMissionStore((s) => s.openMissionId);
  const closeMission = useMissionStore((s) => s.closeMission);

  return (
    <Sheet
      open={openMissionId !== null}
      onOpenChange={(open) => {
        if (!open) closeMission();
      }}
    >
      <SheetContent side="right" className="w-full border-l border-border/50 sm:max-w-2xl">
        <SheetHeader className="border-b border-border/50 pb-2">
          <div className="flex items-center justify-between gap-3">
            <SheetTitle className="truncate font-mono text-[13px]">
              {openMissionId ?? ""}
            </SheetTitle>
            {openMissionId && renderHeaderAction ? renderHeaderAction(openMissionId) : null}
          </div>
        </SheetHeader>
        {openMissionId ? renderBody(openMissionId) : null}
      </SheetContent>
    </Sheet>
  );
}
