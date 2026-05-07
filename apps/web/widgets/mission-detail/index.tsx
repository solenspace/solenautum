"use client";

import type { ReactNode } from "react";

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMissionStore } from "@/features/run-mission";

// `body` and `headerAction` are ReactNodes (not render-prop functions) so
// this widget can be composed from a server component — Next.js 16 RSC
// rejects function props that cross the server→client boundary. Children
// read `openMissionId` from the store themselves; they are only mounted
// while a mission is open.
export interface MissionDetailSlideoverProps {
  body: ReactNode;
  headerAction?: ReactNode;
}

export function MissionDetailSlideover({ body, headerAction }: MissionDetailSlideoverProps) {
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
            {openMissionId && headerAction ? headerAction : null}
          </div>
        </SheetHeader>
        {openMissionId ? body : null}
      </SheetContent>
    </Sheet>
  );
}
