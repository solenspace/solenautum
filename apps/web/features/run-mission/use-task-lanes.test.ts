import type { SseEvent } from "@autumn/sse-protocol";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useTaskLanes } from "./use-task-lanes";

function _ev<T extends SseEvent>(ev: T): T {
  return ev;
}

const _BASE = { mission_id: "m-1" } as const;

describe("useTaskLanes", () => {
  it("returns no lanes for an empty event list", () => {
    const { result } = renderHook(() => useTaskLanes("m-1", []));
    expect(result.current).toEqual([]);
  });

  it("skips mission-level events with no task_id", () => {
    const events: SseEvent[] = [
      _ev({ type: "done", content: { mission_status: "succeeded" }, ..._BASE, seq: 0 } as SseEvent),
    ];
    const { result } = renderHook(() => useTaskLanes("m-1", events));
    expect(result.current).toEqual([]);
  });

  it("projects two tasks in insertion order with correct status, tier, url", () => {
    const events: SseEvent[] = [
      _ev({
        type: "task_start",
        content: { url: "https://a.example", tier: "http" },
        ..._BASE,
        task_id: "t-1",
        seq: 0,
      } as SseEvent),
      _ev({
        type: "task_start",
        content: { url: "https://b.example", tier: "stealth" },
        ..._BASE,
        task_id: "t-2",
        seq: 1,
      } as SseEvent),
      _ev({
        type: "task_end",
        content: { status: "succeeded", preview: "page A", latency_ms: 1234 },
        ..._BASE,
        task_id: "t-1",
        seq: 2,
      } as SseEvent),
    ];
    const { result } = renderHook(() => useTaskLanes("m-1", events));
    expect(result.current).toHaveLength(2);
    expect(result.current[0]?.taskId).toBe("t-1");
    expect(result.current[0]?.url).toBe("https://a.example");
    expect(result.current[0]?.tier).toBe("http");
    expect(result.current[0]?.status).toBe("succeeded");
    expect(result.current[0]?.preview).toBe("page A");
    expect(result.current[0]?.latencyMs).toBe(1234);
    expect(result.current[1]?.taskId).toBe("t-2");
    expect(result.current[1]?.tier).toBe("stealth");
    expect(result.current[1]?.status).toBe("running");
  });

  it("concatenates token events into reasoningTokens per task", () => {
    const events: SseEvent[] = [
      _ev({
        type: "task_start",
        content: { url: "https://a", tier: "http" },
        ..._BASE,
        task_id: "t-1",
        seq: 0,
      } as SseEvent),
      _ev({ type: "token", content: "hel", ..._BASE, task_id: "t-1", seq: 1 } as SseEvent),
      _ev({ type: "token", content: "lo", ..._BASE, task_id: "t-1", seq: 2 } as SseEvent),
      _ev({ type: "token", content: "world", ..._BASE, task_id: "t-2", seq: 3 } as SseEvent),
    ];
    const { result } = renderHook(() => useTaskLanes("m-1", events));
    expect(result.current[0]?.reasoningTokens).toBe("hello");
    expect(result.current[1]?.reasoningTokens).toBe("world");
  });

  it("pairs tool_start with the matching tool_end by tool_name", () => {
    const events: SseEvent[] = [
      _ev({
        type: "task_start",
        content: { url: "https://a", tier: "http" },
        ..._BASE,
        task_id: "t-1",
        seq: 0,
      } as SseEvent),
      _ev({
        type: "tool_start",
        content: { tool_name: "fetch", args: { url: "x" } },
        ..._BASE,
        task_id: "t-1",
        seq: 1,
      } as SseEvent),
      _ev({
        type: "tool_end",
        content: { tool_name: "fetch", duration_ms: 250, ok: true, summary: "200 OK" },
        ..._BASE,
        task_id: "t-1",
        seq: 2,
      } as SseEvent),
    ];
    const { result } = renderHook(() => useTaskLanes("m-1", events));
    const calls = result.current[0]?.toolCalls;
    expect(calls).toHaveLength(1);
    expect(calls?.[0]?.toolName).toBe("fetch");
    expect(calls?.[0]?.ok).toBe(true);
    expect(calls?.[0]?.durationMs).toBe(250);
    expect(calls?.[0]?.summary).toBe("200 OK");
  });

  it("captures errorCode and errorMessage on a typed error event", () => {
    const events: SseEvent[] = [
      _ev({
        type: "task_start",
        content: { url: "https://a", tier: "http" },
        ..._BASE,
        task_id: "t-1",
        seq: 0,
      } as SseEvent),
      _ev({
        type: "error",
        content: { code: "site_not_supported", message: "fronted by Akamai" },
        ..._BASE,
        task_id: "t-1",
        seq: 1,
      } as SseEvent),
    ];
    const { result } = renderHook(() => useTaskLanes("m-1", events));
    expect(result.current[0]?.errorCode).toBe("site_not_supported");
    expect(result.current[0]?.errorMessage).toBe("fronted by Akamai");
  });

  it("keeps startedAt stable across re-projections", () => {
    const initialEvents: SseEvent[] = [
      _ev({
        type: "task_start",
        content: { url: "https://a", tier: "http" },
        ..._BASE,
        task_id: "t-1",
        seq: 0,
      } as SseEvent),
    ];
    const { result, rerender } = renderHook(({ events }) => useTaskLanes("m-1", events), {
      initialProps: { events: initialEvents },
    });
    const startedAt = result.current[0]?.startedAt;
    expect(startedAt).toBeDefined();

    // Wait a real wall-clock tick so Date.now() would change if it were
    // re-stamped, then push a new events array reference.
    const moreEvents: SseEvent[] = [
      ...initialEvents,
      _ev({ type: "token", content: "hi", ..._BASE, task_id: "t-1", seq: 1 } as SseEvent),
    ];
    const before = Date.now();
    while (Date.now() - before < 5) {
      // spin briefly to advance the clock
    }
    rerender({ events: moreEvents });
    expect(result.current[0]?.startedAt).toBe(startedAt);
  });

  it("counts selector_recovered events per lane", () => {
    const events: SseEvent[] = [
      _ev({
        type: "task_start",
        content: { url: "https://a", tier: "http" },
        ..._BASE,
        task_id: "t-1",
        seq: 0,
      } as SseEvent),
      _ev({
        type: "selector_recovered",
        content: { domain: "a", purpose: "main_content", hit_count: 1 },
        ..._BASE,
        task_id: "t-1",
        seq: 1,
      } as SseEvent),
      _ev({
        type: "selector_recovered",
        content: { domain: "a", purpose: "main_content", hit_count: 2 },
        ..._BASE,
        task_id: "t-1",
        seq: 2,
      } as SseEvent),
      _ev({
        type: "task_start",
        content: { url: "https://b", tier: "stealth" },
        ..._BASE,
        task_id: "t-2",
        seq: 3,
      } as SseEvent),
      _ev({
        type: "selector_recovered",
        content: { domain: "b", purpose: "main_content", hit_count: 1 },
        ..._BASE,
        task_id: "t-2",
        seq: 4,
      } as SseEvent),
    ];
    const { result } = renderHook(() => useTaskLanes("m-1", events));
    expect(result.current[0]?.selectorRecoveryCount).toBe(2);
    expect(result.current[1]?.selectorRecoveryCount).toBe(1);
  });
});
