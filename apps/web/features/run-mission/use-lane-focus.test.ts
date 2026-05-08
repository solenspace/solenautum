import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useLaneFocus } from "./use-lane-focus";
import type { TaskLane } from "./use-task-lanes";

function _lane(taskId: string): TaskLane {
  return {
    taskId,
    url: `https://${taskId}.example`,
    tier: "http",
    status: "running",
    reasoningTokens: "",
    toolCalls: [],
    startedAt: 0,
    lastTokenAt: 0,
  };
}

describe("useLaneFocus", () => {
  it("starts at index 0 with an empty pinned set", () => {
    const { result } = renderHook(() => useLaneFocus([_lane("a"), _lane("b"), _lane("c")]));
    expect(result.current.index).toBe(0);
    expect(result.current.pinned.size).toBe(0);
  });

  it("next() advances and wraps at the end", () => {
    const lanes = [_lane("a"), _lane("b"), _lane("c")];
    const { result } = renderHook(() => useLaneFocus(lanes));
    act(() => result.current.next());
    expect(result.current.index).toBe(1);
    act(() => result.current.next());
    act(() => result.current.next());
    expect(result.current.index).toBe(0);
  });

  it("previous() wraps at the top", () => {
    const lanes = [_lane("a"), _lane("b"), _lane("c")];
    const { result } = renderHook(() => useLaneFocus(lanes));
    act(() => result.current.previous());
    expect(result.current.index).toBe(2);
  });

  it("setIndex() clamps out-of-range indices into the lane list", () => {
    const lanes = [_lane("a"), _lane("b")];
    const { result } = renderHook(() => useLaneFocus(lanes));
    act(() => result.current.setIndex(5));
    expect(result.current.index).toBe(1);
    act(() => result.current.setIndex(-1));
    expect(result.current.index).toBe(0);
  });

  it("pin() adds the focused lane and unpin() removes it", () => {
    const lanes = [_lane("a"), _lane("b"), _lane("c")];
    const { result } = renderHook(() => useLaneFocus(lanes));
    act(() => result.current.next());
    act(() => result.current.pin());
    expect(result.current.pinned.has("b")).toBe(true);
    act(() => result.current.unpin());
    expect(result.current.pinned.has("b")).toBe(false);
  });

  it("pin survives setIndex moves so you can pin and navigate away", () => {
    const lanes = [_lane("a"), _lane("b"), _lane("c")];
    const { result } = renderHook(() => useLaneFocus(lanes));
    act(() => result.current.pin());
    act(() => result.current.next());
    expect(result.current.index).toBe(1);
    expect(result.current.pinned.has("a")).toBe(true);
  });

  it("togglePin operates on the supplied taskId, not on the focused lane", () => {
    // Per-row pin button parity: clicking pin on lane "c" while focus is
    // parked on "a" must pin "c", not "a". The earlier shape conflated
    // the two; pin/unpin always acted on the focused lane.
    const lanes = [_lane("a"), _lane("b"), _lane("c")];
    const { result } = renderHook(() => useLaneFocus(lanes));
    expect(result.current.index).toBe(0);
    act(() => result.current.togglePin("c"));
    expect(result.current.pinned.has("c")).toBe(true);
    expect(result.current.pinned.has("a")).toBe(false);
    act(() => result.current.togglePin("c"));
    expect(result.current.pinned.has("c")).toBe(false);
  });

  it("clamps index when the lanes array shrinks below the current index", () => {
    let lanes = [_lane("a"), _lane("b"), _lane("c")];
    const { result, rerender } = renderHook(({ ls }: { ls: TaskLane[] }) => useLaneFocus(ls), {
      initialProps: { ls: lanes },
    });
    act(() => result.current.setIndex(2));
    expect(result.current.index).toBe(2);
    lanes = [_lane("a")];
    rerender({ ls: lanes });
    expect(result.current.index).toBe(0);
  });

  it("falls back to index 0 with no lanes", () => {
    const { result, rerender } = renderHook(({ ls }: { ls: TaskLane[] }) => useLaneFocus(ls), {
      initialProps: { ls: [_lane("a")] },
    });
    rerender({ ls: [] });
    expect(result.current.index).toBe(0);
  });
});
