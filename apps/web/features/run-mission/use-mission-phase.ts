"use client";

import type { SseEvent } from "@autumn/sse-protocol";
import { useMemo } from "react";

import type { MissionPhase } from "@/entities/mission/types";

/**
 * Derives the description-mode phase from the SSE event stream so the
 * slide-over can render the correct child block (discovery list, approval
 * gate, or task lanes) without round-tripping the api on every event.
 *
 * Transitions:
 *   * `done` → `done`
 *   * `task_start` (any) → `scraping`
 *   * `discovery_complete{awaiting_approval=true}` → `awaiting_approval`
 *   * any `url_discovered` (and not already past discovery) → `discovering`
 *
 * Returns `null` when no relevant events have arrived yet — the slide-over
 * shows a connecting placeholder. URL-mode missions never emit
 * `url_discovered` / `discovery_complete`, so they jump straight to
 * `scraping` once the first `task_start` arrives.
 */
export function useMissionPhase(events: SseEvent[]): MissionPhase | null {
  return useMemo(() => {
    let phase: MissionPhase | null = null;
    for (const event of events) {
      switch (event.type) {
        case "url_discovered":
          if (phase === null) phase = "discovering";
          break;
        case "discovery_complete":
          phase = event.content.awaiting_approval ? "awaiting_approval" : phase;
          break;
        case "task_start":
          phase = "scraping";
          break;
        case "done":
          phase = "done";
          break;
        default:
          break;
      }
    }
    return phase;
  }, [events]);
}
