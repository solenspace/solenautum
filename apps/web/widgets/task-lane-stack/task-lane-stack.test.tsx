import type { SseEvent } from "@autumn/sse-protocol";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nTestWrapper } from "@/shared/i18n";

// Mock the mobile hook so desktop assertions stay deterministic. A separate
// describe block flips this for the mobile-specific assertions.
let _isMobileMock = false;
vi.mock("@/shared/hooks/use-mobile", () => ({
  useIsMobile: () => _isMobileMock,
}));

// The orchestrator pulls SSE events from `useMissionStream`. Mocking the
// hook lets the test inject a deterministic events array without touching
// EventSource. `useMissionStream` lives in the run-mission feature barrel,
// so we re-export the rest of the barrel and override only the stream.
let _streamEvents: SseEvent[] = [];
let _streamConnected = true;
let _streamReconnecting = false;
vi.mock("@/features/run-mission", async () => {
  const actual =
    await vi.importActual<typeof import("@/features/run-mission")>("@/features/run-mission");
  return {
    ...actual,
    useMissionStream: () => ({
      events: _streamEvents,
      isConnected: _streamConnected,
      reconnecting: _streamReconnecting,
    }),
  };
});

import { TaskLaneStack } from "./index";

const _MID = "m-1";

function _ev(ev: SseEvent): SseEvent {
  return ev;
}

function _setStream(
  events: SseEvent[],
  state: { isConnected?: boolean; reconnecting?: boolean } = {},
) {
  _streamEvents = events;
  _streamConnected = state.isConnected ?? true;
  _streamReconnecting = state.reconnecting ?? false;
}

function _renderStack() {
  return render(
    <I18nTestWrapper>
      <TaskLaneStack missionId={_MID} />
    </I18nTestWrapper>,
  );
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  _isMobileMock = false;
  _setStream([]);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("TaskLaneStack — desktop", () => {
  it("renders a connecting state when no events have arrived yet", () => {
    _setStream([]);
    _renderStack();
    expect(screen.getByText("Connecting…")).toBeDefined();
  });

  it("renders one lane per task_start in submission order", () => {
    _setStream([
      _ev({
        type: "task_start",
        content: { url: "https://a.example", tier: "http" },
        mission_id: _MID,
        task_id: "t-1",
        seq: 0,
      } as SseEvent),
      _ev({
        type: "task_start",
        content: { url: "https://b.example", tier: "stealth" },
        mission_id: _MID,
        task_id: "t-2",
        seq: 1,
      } as SseEvent),
    ]);
    _renderStack();
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    const [first, second] = items;
    if (!first || !second) throw new Error("expected two listitems");
    expect(within(first).getByText("https://a.example")).toBeDefined();
    expect(within(second).getByText("https://b.example")).toBeDefined();
  });

  it("J advances focus to the next lane and aria-current flips", () => {
    _setStream([
      _ev({
        type: "task_start",
        content: { url: "https://a", tier: "http" },
        mission_id: _MID,
        task_id: "t-1",
        seq: 0,
      } as SseEvent),
      _ev({
        type: "task_start",
        content: { url: "https://b", tier: "http" },
        mission_id: _MID,
        task_id: "t-2",
        seq: 1,
      } as SseEvent),
    ]);
    _renderStack();
    fireEvent.keyDown(window, { key: "j" });
    const focused = screen.getByRole("listitem", { current: true });
    expect(within(focused).getByText("https://b")).toBeDefined();
  });

  it("Enter pins the focused lane (data-user-expanded flips)", () => {
    _setStream([
      _ev({
        type: "task_start",
        content: { url: "https://a", tier: "http" },
        mission_id: _MID,
        task_id: "t-1",
        seq: 0,
      } as SseEvent),
    ]);
    _renderStack();
    fireEvent.keyDown(window, { key: "Enter" });
    const lane = screen.getByRole("listitem", { current: true });
    expect(lane.getAttribute("data-user-expanded")).toBe("true");
  });

  it("aggregate header reflects per-status counts", () => {
    _setStream([
      _ev({
        type: "task_start",
        content: { url: "https://a", tier: "http" },
        mission_id: _MID,
        task_id: "t-1",
        seq: 0,
      } as SseEvent),
      _ev({
        type: "task_end",
        content: { status: "succeeded", preview: "p1" },
        mission_id: _MID,
        task_id: "t-1",
        seq: 1,
      } as SseEvent),
      _ev({
        type: "task_start",
        content: { url: "https://b", tier: "http" },
        mission_id: _MID,
        task_id: "t-2",
        seq: 2,
      } as SseEvent),
      _ev({
        type: "task_end",
        content: { status: "failed", preview: "" },
        mission_id: _MID,
        task_id: "t-2",
        seq: 3,
      } as SseEvent),
    ]);
    _renderStack();
    expect(screen.getByText("1/2")).toBeDefined();
    // 0 streaming, 1 errored.
    expect(screen.getByText("0")).toBeDefined();
    expect(screen.getByText("1")).toBeDefined();
  });

  it("announces lane terminal in the aria-live region", () => {
    // Two lanes: one fails, one stays running, so the mission-complete
    // announcement does not fire and overwrite the lane-terminal one.
    _setStream([
      _ev({
        type: "task_start",
        content: { url: "https://a.example", tier: "http" },
        mission_id: _MID,
        task_id: "t-1",
        seq: 0,
      } as SseEvent),
      _ev({
        type: "task_start",
        content: { url: "https://b.example", tier: "http" },
        mission_id: _MID,
        task_id: "t-2",
        seq: 1,
      } as SseEvent),
      _ev({
        type: "task_end",
        content: { status: "failed", preview: "" },
        mission_id: _MID,
        task_id: "t-1",
        seq: 2,
      } as SseEvent),
    ]);
    _renderStack();
    const region = screen.getByLabelText("Mission status updates");
    expect(region.textContent).toContain("https://a.example");
    expect(region.textContent).toContain("failed");
  });

  it("announces mission complete once every lane has terminated", () => {
    _setStream([
      _ev({
        type: "task_start",
        content: { url: "https://a", tier: "http" },
        mission_id: _MID,
        task_id: "t-1",
        seq: 0,
      } as SseEvent),
      _ev({
        type: "task_end",
        content: { status: "succeeded", preview: "p" },
        mission_id: _MID,
        task_id: "t-1",
        seq: 1,
      } as SseEvent),
    ]);
    _renderStack();
    const region = screen.getByLabelText("Mission status updates");
    expect(region.textContent).toContain("1 of 1 succeeded");
  });
});

describe("TaskLaneStack — mobile", () => {
  beforeEach(() => {
    _isMobileMock = true;
  });

  it("shows only the focused lane and a strip of status dots", () => {
    _setStream([
      _ev({
        type: "task_start",
        content: { url: "https://a", tier: "http" },
        mission_id: _MID,
        task_id: "t-1",
        seq: 0,
      } as SseEvent),
      _ev({
        type: "task_start",
        content: { url: "https://b", tier: "http" },
        mission_id: _MID,
        task_id: "t-2",
        seq: 1,
      } as SseEvent),
    ]);
    _renderStack();
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(1);
    // strip counter "1/2"
    expect(screen.getByText("1/2")).toBeDefined();
  });

  it("J cycles to the next lane on mobile too", () => {
    _setStream([
      _ev({
        type: "task_start",
        content: { url: "https://a", tier: "http" },
        mission_id: _MID,
        task_id: "t-1",
        seq: 0,
      } as SseEvent),
      _ev({
        type: "task_start",
        content: { url: "https://b", tier: "http" },
        mission_id: _MID,
        task_id: "t-2",
        seq: 1,
      } as SseEvent),
    ]);
    _renderStack();
    act(() => {
      fireEvent.keyDown(window, { key: "j" });
    });
    const focused = screen.getByRole("listitem", { current: true });
    expect(within(focused).getByText("https://b")).toBeDefined();
  });
});
