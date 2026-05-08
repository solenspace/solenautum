import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useMissionStream } from "./use-mission-stream";

class _FakeEventSource {
  static instances: _FakeEventSource[] = [];
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  closed = false;
  private _listeners: Map<string, Set<(ev: MessageEvent) => void>> = new Map();

  constructor(url: string) {
    this.url = url;
    _FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, handler: (ev: MessageEvent) => void): void {
    if (!this._listeners.has(type)) this._listeners.set(type, new Set());
    this._listeners.get(type)?.add(handler);
  }

  removeEventListener(type: string, handler: (ev: MessageEvent) => void): void {
    this._listeners.get(type)?.delete(handler);
  }

  close(): void {
    this.closed = true;
  }

  // The api emits each frame with an `event: <type>` line, so a real
  // EventSource fires the typed listener (not `onmessage`). The mock
  // mirrors that: dispatch to the registered typed listeners using the
  // payload's `type`. Pass `useMessageChannel=true` to exercise the
  // un-typed `message` fallback.
  emit(payload: unknown, useMessageChannel = false): void {
    const data = JSON.stringify(payload);
    const ev = new MessageEvent("message", { data });
    if (useMessageChannel) {
      this.onmessage?.(ev);
      return;
    }
    const type =
      typeof payload === "object" && payload !== null && "type" in payload
        ? String((payload as { type?: unknown }).type)
        : "message";
    const listeners = this._listeners.get(type);
    if (listeners && listeners.size > 0) {
      for (const h of listeners) h(ev);
    } else {
      this.onmessage?.(ev);
    }
  }

  emitOpen(): void {
    this.onopen?.(new Event("open"));
  }

  emitError(): void {
    this.onerror?.(new Event("error"));
  }
}

function _instance(index = 0): _FakeEventSource {
  const source = _FakeEventSource.instances[index];
  if (!source) throw new Error(`expected an EventSource at index ${index}`);
  return source;
}

describe("useMissionStream", () => {
  beforeEach(() => {
    _FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", _FakeEventSource);
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("opens fresh when no resume seq exists", () => {
    renderHook(() => useMissionStream("m-1"));
    expect(_FakeEventSource.instances).toHaveLength(1);
    expect(_instance().url).toBe("/api/missions/m-1/stream");
  });

  it("resumes from localStorage seq when present", () => {
    window.localStorage.setItem("autumn:mission:m-2:seq", "42");
    renderHook(() => useMissionStream("m-2"));
    expect(_instance().url).toBe("/api/missions/m-2/stream?after=42");
  });

  it("appends parsed events and persists the latest seq", async () => {
    const { result } = renderHook(() => useMissionStream("m-3"));
    const source = _instance();

    act(() => {
      source.emitOpen();
      source.emit({
        type: "task_start",
        content: { url: "https://example.com/", tier: "http" },
        mission_id: "m-3",
        task_id: "t-1",
        seq: 0,
      });
      source.emit({
        type: "token",
        content: "hello",
        mission_id: "m-3",
        task_id: "t-1",
        seq: 1,
      });
    });

    await waitFor(() => {
      expect(result.current.events).toHaveLength(2);
    });
    expect(result.current.isConnected).toBe(true);
    expect(window.localStorage.getItem("autumn:mission:m-3:seq")).toBe("1");
  });

  it("flips reconnecting on error and stays connected after recover", () => {
    const { result } = renderHook(() => useMissionStream("m-4"));
    const source = _instance();

    act(() => {
      source.emitOpen();
    });
    expect(result.current.isConnected).toBe(true);

    act(() => {
      source.emitError();
    });
    expect(result.current.reconnecting).toBe(true);
    expect(result.current.isConnected).toBe(false);

    act(() => {
      source.emitOpen();
    });
    expect(result.current.reconnecting).toBe(false);
    expect(result.current.isConnected).toBe(true);
  });

  it("rejects malformed events", () => {
    const { result } = renderHook(() => useMissionStream("m-5"));
    const source = _instance();

    act(() => {
      source.emit({ no: "type" });
      source.emit({ type: "token", content: "ok", mission_id: "m-5", seq: 0 });
    });
    expect(result.current.events).toHaveLength(1);
  });

  it("closes on unmount", () => {
    const { unmount } = renderHook(() => useMissionStream("m-6"));
    const source = _instance();
    unmount();
    expect(source.closed).toBe(true);
  });
});
