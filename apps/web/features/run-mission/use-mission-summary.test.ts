import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useMissionSummary } from "./use-mission-summary";
import type { TaskLane } from "./use-task-lanes";

function _lane(overrides: Partial<TaskLane>): TaskLane {
  return {
    taskId: "t-1",
    url: "https://example",
    tier: "http",
    status: "running",
    reasoningTokens: "",
    toolCalls: [],
    startedAt: 1_000,
    lastTokenAt: 0,
    ...overrides,
  };
}

describe("useMissionSummary", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2_000));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("zeroes when no lanes exist", () => {
    const { result } = renderHook(() => useMissionSummary([], false, false));
    expect(result.current.total).toBe(0);
    expect(result.current.elapsedMs).toBe(0);
  });

  it("counts succeeded / running / failed / cancelled / pending", () => {
    const lanes: TaskLane[] = [
      _lane({ taskId: "1", status: "succeeded" }),
      _lane({ taskId: "2", status: "running" }),
      _lane({ taskId: "3", status: "failed" }),
      _lane({ taskId: "4", status: "cancelled" }),
      _lane({ taskId: "5", status: "pending" }),
    ];
    const { result } = renderHook(() => useMissionSummary(lanes, true, false));
    expect(result.current.total).toBe(5);
    expect(result.current.succeeded).toBe(1);
    expect(result.current.running).toBe(1);
    expect(result.current.failed).toBe(1);
    expect(result.current.cancelled).toBe(1);
    expect(result.current.pending).toBe(1);
  });

  it("forwards isConnected and reconnecting from the stream", () => {
    const { result } = renderHook(() => useMissionSummary([], false, true));
    expect(result.current.isConnected).toBe(false);
    expect(result.current.reconnecting).toBe(true);
  });

  it("ticks elapsedMs while any lane is still running", () => {
    const lanes: TaskLane[] = [_lane({ taskId: "1", status: "running", startedAt: 1_000 })];
    const { result } = renderHook(() => useMissionSummary(lanes, true, false));
    expect(result.current.elapsedMs).toBe(1_000); // 2000 - 1000

    // Advance the fake timer by one full tick interval; the setInterval
    // callback re-reads Date.now() so the elapsed clock moves forward.
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(result.current.elapsedMs).toBe(1_500); // 2500 - 1000
  });

  it("freezes elapsedMs once every lane has terminated", () => {
    const lanes: TaskLane[] = [
      _lane({ taskId: "1", status: "succeeded", startedAt: 1_000, finishedAt: 2_400 }),
      _lane({ taskId: "2", status: "failed", startedAt: 1_000, finishedAt: 2_500 }),
    ];
    const { result } = renderHook(() => useMissionSummary(lanes, true, false));
    expect(result.current.elapsedMs).toBe(1_500); // 2500 - 1000

    // Advance the clock; elapsed must not change.
    act(() => {
      vi.setSystemTime(new Date(10_000));
      vi.advanceTimersByTime(2_000);
    });
    expect(result.current.elapsedMs).toBe(1_500);
  });
});
