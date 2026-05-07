"use client";

import { useState } from "react";

import { useT } from "@/shared/i18n";

import { useMissions } from "./use-missions";

/**
 * Mission-level cancel control (Spec 14). Renders a text-button in the
 * slide-over header that issues `DELETE /api/missions/{id}` when the
 * mission is in `running`. The button hides itself for terminal /
 * pending missions; the polled `useMissions` state drives visibility
 * (5s polling is acceptable here — the SSE stream is the source of
 * truth for live UI but the cancel button only needs lifecycle
 * granularity, and reusing the polled state avoids opening a duplicate
 * `EventSource` for the same mission).
 *
 * After a successful DELETE the button does NOT auto-close the
 * slide-over — the user watches the cascading task cancellations land
 * in the lanes and closes the sheet themselves.
 */
export function CancelMissionButton({ missionId }: { missionId: string }) {
  const t = useT();
  const { missions } = useMissions();
  const [pending, setPending] = useState(false);

  const mission = missions.find((m) => m.id === missionId);
  if (!mission || mission.status !== "running") return null;

  async function onCancel(): Promise<void> {
    if (pending) return;
    setPending(true);
    try {
      await fetch(`/api/missions/${missionId}`, { method: "DELETE" });
    } catch {
      // Network blip: the next click retries. The api-side cancel is
      // idempotent so a duplicate DELETE is harmless.
    } finally {
      setPending(false);
    }
  }

  return (
    <button
      type="button"
      onClick={onCancel}
      disabled={pending}
      className="text-[11px] text-muted-foreground transition-colors hover:text-state-error disabled:opacity-50"
    >
      {t("mission", "cancelMission")}
    </button>
  );
}
