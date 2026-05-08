"use client";

import type { SseEvent } from "@autumn/sse-protocol";
import { useEffect, useState } from "react";

import type { MissionRow, TaskRow } from "@/entities/mission/types";

interface MissionDetailState {
  mission: MissionRow | null;
  /**
   * Synthesized SSE events derived from the persisted task list. Lets the
   * `TaskLaneStack` (which renders from events) display lane status,
   * latency, snapshot link, and a markdown excerpt for terminal missions
   * whose ring buffer has already evicted. Live SSE deltas merge on top.
   */
  syntheticEvents: SseEvent[];
  isLoading: boolean;
  error: string | null;
}

const _INITIAL: MissionDetailState = {
  mission: null,
  syntheticEvents: [],
  isLoading: false,
  error: null,
};

/**
 * Fetches `GET /api/missions/{id}` once when `missionId` becomes non-null.
 * The detail endpoint returns the mission row + persisted task list; we
 * convert the task list to SSE-event shape so the existing event-driven
 * widgets (TaskLaneStack, useTaskLanes, etc.) render terminal-mission
 * state without any extra branching at the consumer.
 *
 * The synthesis is deliberate (not a routing change in the SSE protocol):
 * SSE remains the live channel; this hook only patches in the historical
 * baseline that the api's per-mission ring buffer has already discarded.
 */
export function useMissionDetail(missionId: string | null): MissionDetailState {
  const [state, setState] = useState<MissionDetailState>(_INITIAL);

  useEffect(() => {
    if (!missionId) {
      setState(_INITIAL);
      return;
    }

    let cancelled = false;
    setState({ mission: null, syntheticEvents: [], isLoading: true, error: null });

    (async () => {
      try {
        const response = await fetch(`/api/missions/${missionId}`);
        if (!response.ok) {
          if (!cancelled) {
            setState({
              mission: null,
              syntheticEvents: [],
              isLoading: false,
              error: `mission_detail_${response.status}`,
            });
          }
          return;
        }
        const mission = (await response.json()) as MissionRow;
        if (cancelled) return;
        const syntheticEvents = _synthesize(mission);
        setState({ mission, syntheticEvents, isLoading: false, error: null });
      } catch {
        if (cancelled) return;
        setState({
          mission: null,
          syntheticEvents: [],
          isLoading: false,
          error: "mission_detail_fetch_failed",
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [missionId]);

  return state;
}

function _synthesize(mission: MissionRow): SseEvent[] {
  const tasks = mission.tasks ?? [];
  const events: SseEvent[] = [];
  let seq = -1;

  for (const task of tasks) {
    seq += 1;
    events.push(_taskStart(mission.id, task, seq));
    if (task.status !== "pending" && task.status !== "running") {
      seq += 1;
      events.push(_taskEnd(mission.id, task, seq));
    }
  }

  if (
    mission.status === "succeeded" ||
    mission.status === "failed" ||
    mission.status === "cancelled"
  ) {
    seq += 1;
    events.push({
      mission_id: mission.id,
      task_id: null,
      seq,
      type: "done",
      content: { mission_status: mission.status, cost_cents: mission.cost_cents },
    } as unknown as SseEvent);
  }

  return events;
}

function _taskStart(missionId: string, task: TaskRow, seq: number): SseEvent {
  return {
    mission_id: missionId,
    task_id: task.id,
    seq,
    type: "task_start",
    content: { url: task.url, tier: task.tier_used },
  } as unknown as SseEvent;
}

function _taskEnd(missionId: string, task: TaskRow, seq: number): SseEvent {
  // The terminal task event is what the widget reads to populate
  // latency / snapshot / preview. `task_end` content schema is the
  // authoritative shape; mirror only the fields the persisted row
  // actually carries (no real-time markdown, no streamed reasoning).
  return {
    mission_id: missionId,
    task_id: task.id,
    seq,
    type: "task_end",
    content: {
      status: task.status,
      latency_ms: task.latency_ms ?? 0,
      snapshot_key: task.snapshot_key,
      preview: task.parsed_markdown_excerpt,
    },
  } as unknown as SseEvent;
}
