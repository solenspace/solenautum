"use client";

import type { SseEvent, TaskEnd } from "@autumn/sse-protocol";
import { useMemo } from "react";

import { useMissionStream } from "@/features/run-mission";
import { useT } from "@/shared/i18n";

import { ReasoningStream } from "./reasoning-stream";
import { ResultPreview } from "./result-preview";
import { TierBadge } from "./tier-badge";
import { type ToolCall, ToolChip } from "./tool-chip";

type Tier = "http" | "stealth" | "dynamic";

interface Projection {
  tier: Tier;
  url: string | null;
  toolCalls: ToolCall[];
  taskEnd: TaskEnd | null;
}

/**
 * Single task lane. Spec 11 turns this into a stack; for now one mission =
 * one lane = one task, mirroring the api's single-task runner.
 *
 * Projects the SSE event stream into three tiers:
 *   - reasoning (`token` events)        — dim, batched
 *   - tool chips (`tool_start`/`_end`)  — neutral, expandable
 *   - result preview (`task_end`)        — high contrast
 */
export function TaskLaneCard({ missionId }: { missionId: string }) {
  const { events } = useMissionStream(missionId);
  const t = useT();
  const { tier, url, toolCalls, taskEnd } = useMemo(() => _project(events), [events]);

  return (
    <div className="flex flex-col gap-3 p-4">
      <header className="flex items-center gap-2">
        <TierBadge tier={tier} />
        <span className="flex-1 truncate font-mono text-[13px]">
          {url ?? t("mission", "loading")}
        </span>
      </header>

      <ReasoningStream tokens={events} />

      {toolCalls.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {toolCalls.map((call) => (
            <ToolChip key={call.id} call={call} />
          ))}
        </div>
      ) : null}

      {taskEnd ? <ResultPreview taskEnd={taskEnd} /> : null}
    </div>
  );
}

function _project(events: readonly SseEvent[]): Projection {
  let tier: Tier = "http";
  let url: string | null = null;
  let taskEnd: TaskEnd | null = null;
  const calls = new Map<number, ToolCall>();
  let firstTaskStartSeen = false;

  for (const event of events) {
    if (event.type === "task_start" && !firstTaskStartSeen) {
      firstTaskStartSeen = true;
      tier = event.content.tier;
      url = event.content.url;
    } else if (event.type === "tool_start") {
      calls.set(event.seq, {
        id: String(event.seq),
        toolName: event.content.tool_name,
        args: event.content.args,
      });
    } else if (event.type === "tool_end") {
      // Match the most recent unmatched start under this tool_name. Resume
      // after eviction can deliver an end without a paired start; skip those.
      for (const [seq, call] of [...calls].reverse()) {
        if (call.toolName === event.content.tool_name && call.durationMs === undefined) {
          calls.set(seq, {
            ...call,
            durationMs: event.content.duration_ms,
            ok: event.content.ok,
            summary: event.content.summary,
          });
          break;
        }
      }
    } else if (event.type === "task_end" && taskEnd === null) {
      taskEnd = event;
    }
  }

  return { tier, url, taskEnd, toolCalls: [...calls.values()] };
}
