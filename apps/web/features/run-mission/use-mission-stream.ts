"use client";

import type { SseEvent } from "@autumn/sse-protocol";
import { useEffect, useRef, useState } from "react";

const _STORAGE_KEY = (missionId: string): string => `autumn:mission:${missionId}:seq`;

// Mirrors the union of `type` values declared in
// `packages/sse-protocol/generated/types.ts`. The api emits each SSE
// frame with an `event: <type>` line, so the browser dispatches a typed
// event — `onmessage` alone would drop everything.
const _SSE_EVENT_TYPES = [
  "token",
  "tool_start",
  "tool_end",
  "task_start",
  "task_end",
  "url_discovered",
  "discovery_complete",
  "selector_recovered",
  "done",
  "error",
] as const;

export interface MissionStreamState {
  events: SseEvent[];
  isConnected: boolean;
  reconnecting: boolean;
}

const _INITIAL: MissionStreamState = {
  events: [],
  isConnected: false,
  reconnecting: false,
};

/**
 * Single SSE consumer for one mission. Opens an `EventSource` against the
 * BFF stream proxy, threads `Last-Event-ID` through the `?after=<seq>` query
 * parameter (EventSource cannot send custom headers), and persists the last
 * seen `seq` to `localStorage` so a fresh tab on the same mission resumes
 * from the ring buffer rather than replaying from zero.
 *
 * The hook intentionally does not trigger reconnects manually — the browser's
 * native `EventSource` does that on network drops with its own backoff —
 * but it surfaces the reconnect state via `state.reconnecting` so the UI can
 * render a transient indicator.
 */
export function useMissionStream(missionId: string | null): MissionStreamState {
  const [state, setState] = useState<MissionStreamState>(_INITIAL);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!missionId) {
      setState(_INITIAL);
      return;
    }

    let cancelled = false;
    const lastSeq = _readLastSeq(missionId);
    const url =
      lastSeq != null
        ? `/api/missions/${missionId}/stream?after=${lastSeq}`
        : `/api/missions/${missionId}/stream`;
    const es = new EventSource(url);
    sourceRef.current = es;

    es.onopen = () => {
      if (cancelled) return;
      setState((prev) => ({ ...prev, isConnected: true, reconnecting: false }));
    };

    es.onerror = () => {
      if (cancelled) return;
      setState((prev) => ({ ...prev, isConnected: false, reconnecting: true }));
      // EventSource auto-reconnects with its own backoff; do not recreate.
    };

    // The api emits each event with an `event: <type>` line, so the
    // browser dispatches a typed `task_start` / `task_end` / `done` /
    // `error` / `tool_start` / `tool_end` / `token` / `url_discovered` /
    // `discovery_complete` / `selector_recovered` event — never the
    // default `message`. Listening only on `onmessage` would drop every
    // event and leave the slide-over stuck at "Connecting…".
    const handleEventData = (data: string): void => {
      if (cancelled) return;
      let raw: unknown;
      try {
        raw = JSON.parse(data);
      } catch {
        return;
      }
      const parsed = _parseSseEvent(raw);
      if (parsed === null) return;
      _writeLastSeq(missionId, parsed.seq);
      setState((prev) => ({ ...prev, events: [...prev.events, parsed] }));
    };

    const _listener = (event: MessageEvent): void => handleEventData(event.data);

    for (const eventType of _SSE_EVENT_TYPES) {
      es.addEventListener(eventType, _listener as EventListener);
    }
    // Also handle the default `message` channel for any future un-typed
    // event (and the resume-lost synthetic the api still emits with no
    // explicit `event:` line, if any).
    es.onmessage = _listener;

    return () => {
      cancelled = true;
      for (const eventType of _SSE_EVENT_TYPES) {
        es.removeEventListener(eventType, _listener as EventListener);
      }
      es.close();
      sourceRef.current = null;
    };
  }, [missionId]);

  return state;
}

function _readLastSeq(missionId: string): number | null {
  try {
    const value = localStorage.getItem(_STORAGE_KEY(missionId));
    if (value == null) return null;
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function _writeLastSeq(missionId: string, seq: number): void {
  try {
    localStorage.setItem(_STORAGE_KEY(missionId), String(seq));
  } catch {
    // localStorage unavailable (private mode, quota); resume won't work but
    // the live stream still runs because seq tracking is local-only.
  }
}

function _parseSseEvent(raw: unknown): SseEvent | null {
  // Minimal validation. The api's emitter is the only producer and the
  // codegen-derived types in `@autumn/sse-protocol` describe the contract;
  // the consumer trusts the producer. This guard exists so a future
  // adversarial event (or a partial outage replay) does not crash the UI.
  if (typeof raw !== "object" || raw === null) return null;
  const candidate = raw as Record<string, unknown>;
  if (typeof candidate.type !== "string") return null;
  if (typeof candidate.mission_id !== "string") return null;
  if (typeof candidate.seq !== "number") return null;
  return raw as SseEvent;
}
