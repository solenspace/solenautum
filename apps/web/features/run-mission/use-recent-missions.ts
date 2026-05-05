"use client";

import type { MissionRow } from "@/entities/mission/types";

import { useMissions } from "./use-missions";

/**
 * Last 3 terminal missions, newest first. The api returns `created_at DESC`
 * already, so we only need to filter and slice. Used by the command palette
 * `Recent` section.
 */
export function useRecentMissions(): MissionRow[] {
  const { missions } = useMissions();
  return missions
    .filter((m) => m.status === "succeeded" || m.status === "failed" || m.status === "cancelled")
    .slice(0, 3);
}
