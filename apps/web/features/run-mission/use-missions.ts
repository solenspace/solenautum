"use client";

import { useEffect, useMemo, useState } from "react";

import type { MissionRow, MissionStatus } from "@/entities/mission/types";

const POLL_INTERVAL_MS = 5_000;

/**
 * Sidebar-bucket axis. Adds `awaiting_approval` to the lifecycle status
 * (Spec 14): a description-mode mission whose `status === "running"` and
 * `phase === "awaiting_approval"` lands in this synthetic group so the
 * user can spot parked-on-approval missions at a glance.
 */
export type MissionBucket = MissionStatus | "awaiting_approval";

export type MissionsByStatus = Record<MissionBucket, MissionRow[]>;

interface UseMissionsState {
  missions: MissionRow[];
  byStatus: MissionsByStatus;
  isLoading: boolean;
}

function _bucketOf(row: MissionRow): MissionBucket {
  if (row.status === "running" && row.phase === "awaiting_approval") {
    return "awaiting_approval";
  }
  return row.status;
}

function _group(rows: readonly MissionRow[]): MissionsByStatus {
  const out: MissionsByStatus = {
    pending: [],
    running: [],
    awaiting_approval: [],
    succeeded: [],
    failed: [],
    cancelled: [],
  };
  for (const row of rows) {
    out[_bucketOf(row)].push(row);
  }
  return out;
}

// Module-level poll registry. One timer feeds N consumers so adding
// `useMissions()` to another component doesn't double the network load.
// The previous shape opened a separate poll loop per `useEffect` mount,
// which under React StrictMode + ~5 simultaneous consumers (sidebar,
// cancel button, welcome card, recent-missions widget) hit the BFF rate
// limit well inside a single live mission.
type _Listener = (rows: MissionRow[]) => void;
const _listeners = new Set<_Listener>();
let _missions: MissionRow[] = [];
let _hasFetched = false;
let _timer: ReturnType<typeof setTimeout> | null = null;
let _inflight: Promise<void> | null = null;

function _broadcast(): void {
  for (const fn of _listeners) fn(_missions);
}

async function _fetchOnce(): Promise<void> {
  if (_inflight) return _inflight;
  _inflight = (async () => {
    try {
      const response = await fetch("/api/missions");
      if (!response.ok) return;
      const payload = (await response.json()) as { missions: MissionRow[] };
      _missions = payload.missions;
      _hasFetched = true;
      _broadcast();
    } catch {
      // Network blips are normal during reconnect; consumers keep last good state.
    } finally {
      _inflight = null;
    }
  })();
  return _inflight;
}

function _schedule(): void {
  if (_timer) return;
  _timer = setTimeout(() => {
    _timer = null;
    if (typeof document !== "undefined" && document.visibilityState === "visible") {
      void _fetchOnce();
    }
    if (_listeners.size > 0) _schedule();
  }, POLL_INTERVAL_MS);
}

function _onVisibility(): void {
  if (typeof document !== "undefined" && document.visibilityState === "visible") {
    void _fetchOnce();
  }
}

let _visibilityHooked = false;
function _ensureVisibilityHook(): void {
  if (_visibilityHooked || typeof document === "undefined") return;
  _visibilityHooked = true;
  document.addEventListener("visibilitychange", _onVisibility);
}

/**
 * Polls the BFF mission list every 5 seconds, shared across every caller.
 * The first `useMissions()` consumer arms the timer; later consumers
 * subscribe to the shared cache. The timer halts when the last consumer
 * unmounts so a torn-down view doesn't keep the network warm.
 *
 * Polling pauses while the document is hidden — there's nobody to update.
 * The next visibility change triggers an immediate refetch so a returning
 * user sees fresh state without waiting another tick.
 */
export function useMissions(): UseMissionsState {
  const [missions, setMissions] = useState<MissionRow[]>(_missions);
  const [isLoading, setLoading] = useState(!_hasFetched);

  useEffect(() => {
    _ensureVisibilityHook();
    const listener: _Listener = (rows) => {
      setMissions(rows);
      setLoading(false);
    };
    _listeners.add(listener);
    if (!_hasFetched) {
      void _fetchOnce().then(() => setLoading(false));
    } else {
      // First listener after a hot reload may already have data.
      setMissions(_missions);
      setLoading(false);
    }
    _schedule();
    return () => {
      _listeners.delete(listener);
    };
  }, []);

  const byStatus = useMemo(() => _group(missions), [missions]);

  return { missions, byStatus, isLoading };
}
