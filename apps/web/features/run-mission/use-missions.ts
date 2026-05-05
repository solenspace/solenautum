"use client";

import { useEffect, useMemo, useState } from "react";

import type { MissionRow, MissionStatus } from "@/entities/mission/types";

const POLL_INTERVAL_MS = 5_000;

export type MissionsByStatus = Record<MissionStatus, MissionRow[]>;

interface UseMissionsState {
  missions: MissionRow[];
  byStatus: MissionsByStatus;
  isLoading: boolean;
}

function _group(rows: readonly MissionRow[]): MissionsByStatus {
  const out: MissionsByStatus = {
    pending: [],
    running: [],
    succeeded: [],
    failed: [],
    cancelled: [],
  };
  for (const row of rows) {
    out[row.status].push(row);
  }
  return out;
}

/**
 * Polls the BFF mission list every 5 seconds. Spec 14 swaps polling for a
 * server-push invalidation, but for Spec 08 the cost (one round-trip per
 * 5s) is below the per-user rate limit by an order of magnitude.
 *
 * Polling pauses while the document is hidden — there's nobody to update.
 * The next visibility change triggers an immediate refetch so a returning
 * user sees fresh state without waiting another tick.
 */
export function useMissions(): UseMissionsState {
  const [missions, setMissions] = useState<MissionRow[]>([]);
  const [isLoading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function fetchOnce(): Promise<void> {
      try {
        const response = await fetch("/api/missions");
        if (!response.ok || cancelled) return;
        const payload = (await response.json()) as { missions: MissionRow[] };
        if (!cancelled) setMissions(payload.missions);
      } catch {
        // Network blips are normal during reconnect; sidebar keeps last good state.
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    function schedule(): void {
      if (cancelled) return;
      timer = setTimeout(async () => {
        if (document.visibilityState === "visible") await fetchOnce();
        schedule();
      }, POLL_INTERVAL_MS);
    }

    function onVisibility(): void {
      if (document.visibilityState === "visible") void fetchOnce();
    }

    void fetchOnce();
    schedule();
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  const byStatus = useMemo(() => _group(missions), [missions]);

  return { missions, byStatus, isLoading };
}
