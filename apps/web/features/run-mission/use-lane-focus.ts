"use client";

import { useCallback, useEffect, useState } from "react";

import type { TaskLane } from "./use-task-lanes";

export interface LaneFocus {
  /** Index of the focused lane. Always within `[0, lanes.length)` while lanes exist. */
  index: number;
  /** Set of `taskId`s the user has explicitly pinned with Enter. */
  pinned: Set<string>;
  next: () => void;
  previous: () => void;
  setIndex: (i: number) => void;
  /** Add the currently-focused lane to the pinned set (Enter shortcut). */
  pin: () => void;
  /** Remove the currently-focused lane from the pinned set (x shortcut). */
  unpin: () => void;
  /**
   * Toggle the pinned state of an arbitrary lane by `taskId`. Used by the
   * per-row pin button so clicking pin on lane 5 acts on lane 5, not on
   * whatever lane J/K focus happens to be parked on.
   */
  togglePin: (taskId: string) => void;
}

/**
 * Tracks J/K lane navigation and Enter-pin / x-unpin state. Wraps at top
 * and bottom; clamps `index` when the lanes array shrinks.
 *
 * `pinned` is keyed on `taskId` rather than index so a user-pinned lane
 * survives any future reordering.
 */
export function useLaneFocus(lanes: TaskLane[]): LaneFocus {
  const [index, setIndexInternal] = useState(0);
  const [pinned, setPinned] = useState<Set<string>>(() => new Set());
  const length = lanes.length;
  const focusedTaskId = lanes[index]?.taskId;

  useEffect(() => {
    if (length === 0) {
      if (index !== 0) setIndexInternal(0);
      return;
    }
    if (index >= length) {
      setIndexInternal(length - 1);
    }
  }, [length, index]);

  const next = useCallback(() => {
    setIndexInternal((i) => (length === 0 ? 0 : (i + 1) % length));
  }, [length]);

  const previous = useCallback(() => {
    setIndexInternal((i) => (length === 0 ? 0 : (i - 1 + length) % length));
  }, [length]);

  const setIndex = useCallback(
    (i: number) => {
      if (length === 0) {
        setIndexInternal(0);
        return;
      }
      const clamped = Math.max(0, Math.min(i, length - 1));
      setIndexInternal(clamped);
    },
    [length],
  );

  const pin = useCallback(() => {
    if (!focusedTaskId) return;
    setPinned((prev) => {
      if (prev.has(focusedTaskId)) return prev;
      const out = new Set(prev);
      out.add(focusedTaskId);
      return out;
    });
  }, [focusedTaskId]);

  const unpin = useCallback(() => {
    if (!focusedTaskId) return;
    setPinned((prev) => {
      if (!prev.has(focusedTaskId)) return prev;
      const out = new Set(prev);
      out.delete(focusedTaskId);
      return out;
    });
  }, [focusedTaskId]);

  const togglePin = useCallback((taskId: string) => {
    setPinned((prev) => {
      const out = new Set(prev);
      if (out.has(taskId)) out.delete(taskId);
      else out.add(taskId);
      return out;
    });
  }, []);

  return { index, pinned, next, previous, setIndex, pin, unpin, togglePin };
}
