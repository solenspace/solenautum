"use client";

import { Sidebar, SidebarContent, SidebarGroup, SidebarHeader } from "@/components/ui/sidebar";
import { useMissions } from "@/features/run-mission";
import { useT } from "@/shared/i18n";

import { MissionRow } from "./mission-row";

const _GROUPS = ["running", "pending", "succeeded", "failed", "cancelled"] as const;

const _GROUP_LABEL = {
  running: "status_running",
  pending: "status_pending",
  succeeded: "status_succeeded",
  failed: "status_failed",
  cancelled: "status_cancelled",
} as const;

export function MissionSidebar() {
  const t = useT();
  const { byStatus } = useMissions();

  return (
    <Sidebar className="border-r border-border/50">
      <SidebarHeader className="px-3 py-2 text-[11px] uppercase tracking-wide text-muted-foreground/70">
        {t("mission", "yourMissions")}
      </SidebarHeader>
      <SidebarContent>
        {_GROUPS.map((status) => {
          const items = byStatus[status];
          if (items.length === 0) return null;
          return (
            <SidebarGroup key={status}>
              <div className="px-3 pt-2 text-[11px] uppercase tracking-wide text-muted-foreground/70">
                {t("mission", _GROUP_LABEL[status])}
              </div>
              {items.map((mission) => (
                <MissionRow key={mission.id} mission={mission} />
              ))}
            </SidebarGroup>
          );
        })}
      </SidebarContent>
    </Sidebar>
  );
}
