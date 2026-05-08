"use client";

import type { ReactNode } from "react";

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMissionDetail, useMissionStore } from "@/features/run-mission";

// `body` and `headerAction` are ReactNodes (not render-prop functions) so
// this widget can be composed from a server component — Next.js 16 RSC
// rejects function props that cross the server→client boundary. Children
// read `openMissionId` from the store themselves; they are only mounted
// while a mission is open.
export interface MissionDetailSlideoverProps {
  body: ReactNode;
  headerAction?: ReactNode;
}

const _TITLE_MAX_CHARS = 96;

function _missionTitle(prompt: string | undefined, missionId: string | null): string {
  if (!prompt) return missionId?.slice(0, 8) ?? "";
  // Description-mode prompts are user prose; URL-mode prompts are a
  // newline-separated URL list. Either way, keep the first line and
  // truncate so the header stays one line on every viewport.
  const firstLine = prompt.split("\n")[0]?.trim() ?? "";
  if (firstLine.length <= _TITLE_MAX_CHARS) return firstLine;
  return `${firstLine.slice(0, _TITLE_MAX_CHARS - 1)}…`;
}

export function MissionDetailSlideover({ body, headerAction }: MissionDetailSlideoverProps) {
  const openMissionId = useMissionStore((s) => s.openMissionId);
  const closeMission = useMissionStore((s) => s.closeMission);
  const detail = useMissionDetail(openMissionId);

  const title = _missionTitle(detail.mission?.prompt, openMissionId);

  return (
    <Sheet
      open={openMissionId !== null}
      onOpenChange={(open) => {
        if (!open) closeMission();
      }}
    >
      {/*
        The shadcn Sheet primitive applies `data-[side=right]:sm:max-w-sm`
        which beats a plain `sm:max-w-2xl` (data-attribute selector wins
        on specificity). Match the modifier so the consumer override
        actually takes effect, and step the cap up at lg/xl so the slide-
        over has room for markdown previews on real laptop displays.
      */}
      <SheetContent
        side="right"
        className="w-full border-l border-border/50 data-[side=right]:sm:max-w-2xl data-[side=right]:lg:max-w-3xl data-[side=right]:xl:max-w-4xl"
      >
        <SheetHeader className="border-b border-border/50 pb-2">
          <div className="flex items-center justify-between gap-3">
            <SheetTitle
              className="truncate text-sm font-medium text-foreground"
              title={detail.mission?.prompt ?? openMissionId ?? undefined}
            >
              {title}
            </SheetTitle>
            {openMissionId && headerAction ? headerAction : null}
          </div>
        </SheetHeader>
        {openMissionId ? body : null}
      </SheetContent>
    </Sheet>
  );
}
