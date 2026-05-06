"use client";

import { useEffect, useState } from "react";

import type { TaskLane } from "./use-task-lanes";

export interface MissionSummary {
  total: number;
  succeeded: number;
  running: number;
  failed: number;
  cancelled: number;
  pending: number;
  elapsedMs: number;
  /** True once the SSE EventSource has emitted `open`. */
  isConnected: boolean;
  /** True while EventSource has fired `error` and is auto-retrying. */
  reconnecting: boolean;
}

/**
 * Aggregates per-lane state for the sticky mission header. The elapsed
 * clock ticks every 500ms while any lane is non-terminal and freezes at
 * the latest `finishedAt` once every lane terminates — operators reading
 * a failed mission see the final wall-clock duration, not a perpetually
 * counting timer.
 */
export function useMissionSummary(
  lanes: TaskLane[],
  isConnected: boolean,
  reconnecting: boolean,
): MissionSummary {
  let succeeded = 0;
  let running = 0;
  let failed = 0;
  let cancelled = 0;
  let pending = 0;
  let allTerminal = lanes.length > 0;
  let maxStop = 0;
  for (const lane of lanes) {
    switch (lane.status) {
      case "succeeded":
        succeeded += 1;
        break;
      case "running":
        running += 1;
        allTerminal = false;
        break;
      case "failed":
        failed += 1;
        break;
      case "cancelled":
        cancelled += 1;
        break;
      case "pending":
        pending += 1;
        allTerminal = false;
        break;
    }
    const stop = lane.finishedAt ?? lane.startedAt;
    if (stop > maxStop) maxStop = stop;
  }

  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (allTerminal || lanes.length === 0) return;
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, [allTerminal, lanes.length]);

  let elapsedMs = 0;
  if (lanes.length > 0) {
    const startedAt = lanes[0]?.startedAt ?? now;
    const stopAt = allTerminal ? maxStop : now;
    elapsedMs = Math.max(0, stopAt - startedAt);
  }

  return {
    total: lanes.length,
    succeeded,
    running,
    failed,
    cancelled,
    pending,
    elapsedMs,
    isConnected,
    reconnecting,
  };
}
