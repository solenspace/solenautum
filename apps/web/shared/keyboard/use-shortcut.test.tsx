import { fireEvent, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useShortcut } from "./index";

describe("useShortcut", () => {
  it("fires when the combo matches", () => {
    const handler = vi.fn();
    renderHook(() => {
      useShortcut("cmd+k", handler);
    });

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("normalizes ⌘ symbol and ctrl alias", () => {
    const handler = vi.fn();
    renderHook(() => {
      useShortcut(["⌘k", "ctrl+k"], handler);
    });

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(handler).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(handler).toHaveBeenCalledTimes(2);
  });

  it("does not fire on a different key", () => {
    const handler = vi.fn();
    renderHook(() => {
      useShortcut("cmd+k", handler);
    });

    fireEvent.keyDown(window, { key: "j", metaKey: true });
    expect(handler).not.toHaveBeenCalled();
  });

  it("ignores events from editable targets by default", () => {
    const handler = vi.fn();
    renderHook(() => {
      useShortcut("escape", handler);
    });

    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: "Escape" });
    expect(handler).not.toHaveBeenCalled();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(handler).toHaveBeenCalledTimes(1);

    document.body.removeChild(input);
  });

  it("allows editable-target events when opted in", () => {
    const handler = vi.fn();
    renderHook(() => {
      useShortcut("cmd+enter", handler, { allowInInput: true });
    });

    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: "Enter", metaKey: true });
    expect(handler).toHaveBeenCalledTimes(1);

    document.body.removeChild(input);
  });

  it("removes the listener on unmount", () => {
    const handler = vi.fn();
    const { unmount } = renderHook(() => {
      useShortcut("cmd+k", handler);
    });

    unmount();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(handler).not.toHaveBeenCalled();
  });
});
