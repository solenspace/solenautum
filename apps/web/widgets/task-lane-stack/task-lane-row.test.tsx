import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TaskLane } from "@/features/run-mission";
import { I18nTestWrapper } from "@/shared/i18n";

import { TaskLaneRow } from "./task-lane-row";

function _lane(overrides: Partial<TaskLane> = {}): TaskLane {
  return {
    taskId: "t-1",
    url: "https://example.com/page",
    tier: "http",
    status: "running",
    reasoningTokens: "thinking…",
    toolCalls: [],
    startedAt: 0,
    lastTokenAt: 0,
    ...overrides,
  };
}

function _render(
  lane: TaskLane,
  props: { isFocused: boolean; isPinned: boolean } = {
    isFocused: false,
    isPinned: false,
  },
) {
  return render(
    <I18nTestWrapper>
      <ul>
        <TaskLaneRow
          lane={lane}
          isFocused={props.isFocused}
          isPinned={props.isPinned}
          onFocus={() => {}}
        />
      </ul>
    </I18nTestWrapper>,
  );
}

describe("TaskLaneRow", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("renders the URL and tier", () => {
    _render(_lane());
    expect(screen.getByText("https://example.com/page")).toBeDefined();
    expect(screen.getByText("HT")).toBeDefined();
  });

  it("is expanded by default while running so reasoning shows", () => {
    _render(_lane({ reasoningTokens: "running thoughts" }));
    expect(screen.getByText("running thoughts")).toBeDefined();
  });

  it("stays expanded on failed status", () => {
    _render(
      _lane({
        status: "failed",
        finishedAt: Date.now(),
        reasoningTokens: "broken",
        errorCode: "render_timeout",
        errorMessage: "ignored",
      }),
    );
    expect(screen.getByText("broken")).toBeDefined();
    expect(screen.getByText("Page took too long to render.")).toBeDefined();
  });

  it("collapses 1.5s after a succeeded terminal", () => {
    vi.useFakeTimers();
    const finishedAt = Date.now();
    _render(_lane({ status: "succeeded", finishedAt, reasoningTokens: "done thoughts" }));
    expect(screen.getByText("done thoughts")).toBeDefined();
    act(() => {
      vi.advanceTimersByTime(1_600);
    });
    expect(screen.queryByText("done thoughts")).toBeNull();
  });

  it("stays expanded after success when pinned", () => {
    vi.useFakeTimers();
    _render(
      _lane({
        status: "succeeded",
        finishedAt: Date.now(),
        reasoningTokens: "pinned thoughts",
      }),
      { isFocused: false, isPinned: true },
    );
    act(() => {
      vi.advanceTimersByTime(2_000);
    });
    expect(screen.getByText("pinned thoughts")).toBeDefined();
  });

  it("flips aria-current with focus", () => {
    const { rerender } = render(
      <I18nTestWrapper>
        <ul>
          <TaskLaneRow lane={_lane()} isFocused={false} isPinned={false} onFocus={() => {}} />
        </ul>
      </I18nTestWrapper>,
    );
    expect(screen.queryByRole("listitem", { current: true })).toBeNull();
    rerender(
      <I18nTestWrapper>
        <ul>
          <TaskLaneRow lane={_lane()} isFocused={true} isPinned={false} onFocus={() => {}} />
        </ul>
      </I18nTestWrapper>,
    );
    const focused = screen.getByRole("listitem", { current: true });
    expect(focused).toBeDefined();
  });

  it("shows the latency value on a finished lane", () => {
    _render(_lane({ status: "succeeded", latencyMs: 2_400, finishedAt: Date.now() }));
    expect(screen.getByText("2.4s")).toBeDefined();
  });
});
