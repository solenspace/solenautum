"use client";

import type { SseEvent } from "@autumn/sse-protocol";
import { useMemo, useRef } from "react";

import type { MissionStatus } from "@/entities/mission/types";

type Tier = "http" | "stealth" | "dynamic";

export interface ToolCall {
  id: string;
  toolName: string;
  args?: Record<string, unknown>;
  durationMs?: number;
  ok?: boolean;
  summary?: string;
}

export interface TaskLane {
  taskId: string;
  url: string;
  tier: Tier;
  status: MissionStatus;
  reasoningTokens: string;
  toolCalls: ToolCall[];
  preview?: string;
  latencyMs?: number;
  errorCode?: string;
  errorMessage?: string;
  /** Wall-clock when the lane's first event arrived. Stable across re-projections. */
  startedAt: number;
  /** Wall-clock of the most recent token, or 0 if none. Stable across re-projections. */
  lastTokenAt: number;
  /** Wall-clock when the lane terminated, or undefined while running. Stable. */
  finishedAt?: number;
  /** Count of `selector_recovered` events seen for this task. Drives the
   * inline "selectors recovered" chip in the lane body (Spec 13). */
  selectorRecoveryCount?: number;
}

interface _LaneTimes {
  startedAt: number;
  /** Tokens seen so far for this task; only newly-arrived tokens advance lastTokenAt. */
  tokenCount: number;
  lastTokenAt: number;
  finishedAt?: number;
}

/**
 * Projects the SSE event log into per-task lanes in submission order.
 *
 * Wall-clock timestamps live in a `useRef<Map>` *outside* the `useMemo` —
 * a fresh `Date.now()` inside the projection would shift them forward on
 * every re-projection, breaking the 5s-idle reasoning collapse and the
 * elapsed clock. `startedAt` stamps once per task, `lastTokenAt` advances
 * only when the per-task token count grows past the previously recorded
 * count, `finishedAt` stamps on the first terminal event.
 */
export function useTaskLanes(missionId: string | null, events: SseEvent[]): TaskLane[] {
  const timesRef = useRef<Map<string, _LaneTimes>>(new Map());
  const lastMissionIdRef = useRef<string | null>(null);

  // Clear stale per-task timestamps synchronously when the slide-over swaps
  // to a different mission, so the upcoming projection can't reuse a
  // previous mission's timestamps for a colliding task_id.
  if (lastMissionIdRef.current !== missionId) {
    timesRef.current.clear();
    lastMissionIdRef.current = missionId;
  }

  return useMemo(() => {
    const times = timesRef.current;
    const byTaskId = new Map<string, TaskLane>();
    const projectionTokenCounts = new Map<string, number>();

    for (const ev of events) {
      const taskId = typeof ev.task_id === "string" ? ev.task_id : null;
      if (taskId === null) continue;

      let stamps = times.get(taskId);
      if (!stamps) {
        stamps = { startedAt: Date.now(), tokenCount: 0, lastTokenAt: 0 };
        times.set(taskId, stamps);
      }

      let lane = byTaskId.get(taskId);
      if (!lane) {
        lane = {
          taskId,
          url: "",
          tier: "http",
          status: "pending",
          reasoningTokens: "",
          toolCalls: [],
          startedAt: stamps.startedAt,
          lastTokenAt: stamps.lastTokenAt,
          finishedAt: stamps.finishedAt,
        };
        byTaskId.set(taskId, lane);
      }

      switch (ev.type) {
        case "task_start":
          lane.url = ev.content.url;
          lane.tier = ev.content.tier;
          lane.status = "running";
          break;
        case "token":
          lane.reasoningTokens += ev.content;
          projectionTokenCounts.set(taskId, (projectionTokenCounts.get(taskId) ?? 0) + 1);
          break;
        case "tool_start":
          lane.toolCalls.push({
            id: String(ev.seq),
            toolName: ev.content.tool_name,
            args: ev.content.args,
          });
          break;
        case "tool_end": {
          // Match the most recent unmatched start under this tool_name. Ring-
          // buffer eviction can deliver an end without a paired start; those
          // land here as no-ops.
          for (let i = lane.toolCalls.length - 1; i >= 0; i -= 1) {
            const call = lane.toolCalls[i];
            if (call && call.toolName === ev.content.tool_name && call.ok === undefined) {
              lane.toolCalls[i] = {
                ...call,
                durationMs: ev.content.duration_ms,
                ok: ev.content.ok,
                summary: ev.content.summary,
              };
              break;
            }
          }
          break;
        }
        case "task_end":
          lane.status = ev.content.status;
          lane.preview = ev.content.preview;
          lane.latencyMs = ev.content.latency_ms;
          if (stamps.finishedAt === undefined) {
            stamps.finishedAt = Date.now();
          }
          lane.finishedAt = stamps.finishedAt;
          break;
        case "error":
          lane.errorCode = ev.content.code;
          lane.errorMessage = ev.content.message;
          break;
        case "selector_recovered":
          lane.selectorRecoveryCount = (lane.selectorRecoveryCount ?? 0) + 1;
          break;
      }
    }

    // Advance lastTokenAt for any task whose token count grew this projection.
    for (const lane of byTaskId.values()) {
      const stamps = times.get(lane.taskId);
      if (!stamps) continue;
      const count = projectionTokenCounts.get(lane.taskId) ?? 0;
      if (count > stamps.tokenCount) {
        stamps.tokenCount = count;
        stamps.lastTokenAt = Date.now();
      }
      lane.lastTokenAt = stamps.lastTokenAt;
    }

    return Array.from(byTaskId.values());
  }, [events]);
}

/**
 * Lane status → Tailwind class for the small dot used in `TaskLaneRow`,
 * the mobile lane strip, and `lane-skeleton.tsx`. Centralised here so
 * the colour mapping stays in one place.
 */
export function laneStatusDotClass(
  status: MissionStatus,
  options: { pulse?: boolean } = {},
): string {
  switch (status) {
    case "running":
      return options.pulse === false ? "bg-primary" : "bg-primary animate-pulse";
    case "succeeded":
      return "bg-state-success";
    case "failed":
      return "bg-state-error";
    case "cancelled":
      return "bg-muted-foreground/60";
    default:
      return "bg-muted-foreground/40";
  }
}
