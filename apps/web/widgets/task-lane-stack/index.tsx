"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { useSwipeable } from "react-swipeable";

import {
  laneStatusDotClass,
  type MissionStreamState,
  type TaskLane,
  useLaneFocus,
  useMissionSummary,
  useTaskCancel,
  useTaskLanes,
} from "@/features/run-mission";
import { useIsMobile } from "@/shared/hooks/use-mobile";
import { useT } from "@/shared/i18n";
import { useShortcut } from "@/shared/keyboard";
import { cn } from "@/shared/utils/cn";

import { AggregateHeader } from "./aggregate-header";
import { LaneSkeleton } from "./lane-skeleton";
import { TaskLaneRow } from "./task-lane-row";

/**
 * Multi-lane SSE renderer. Owns the J/K/Enter/x shortcut bindings, the
 * mobile single-lane swipe behaviour, and the mission-level
 * `aria-live="polite"` announcement region. Lane bodies use
 * `aria-live="off"` so screen readers only read a lane on intentional
 * navigation; per-token announcements would be unusable at any N.
 */
// `stream` is supplied by the parent (the slide-over) so this widget
// reads from the SAME `useMissionStream` subscription that drives the
// phase-aware container. The flagship rule is "single SSE consumer per
// mission" (`code-standards.md` and `architecture.md`); calling
// `useMissionStream` here too would open a second EventSource with
// independent React state and the lanes would never see the events
// already drained into the parent's state.
export function TaskLaneStack({
  missionId,
  stream,
}: {
  missionId: string;
  stream: MissionStreamState;
}) {
  const t = useT();
  const lanes = useTaskLanes(missionId, stream.events);
  const summary = useMissionSummary(lanes, stream.isConnected, stream.reconnecting);
  const focus = useLaneFocus(lanes);
  const isMobile = useIsMobile();
  const { cancelTask } = useTaskCancel();

  useShortcut("j", () => focus.next());
  useShortcut("k", () => focus.previous());
  useShortcut("Enter", () => focus.pin());
  // Spec 14: X is now state-aware — cancel a still-running lane, fall
  // through to unpin for terminal lanes. Decision lives in the widget so
  // `useLaneFocus` stays focused on focus/pin state and need not know
  // anything about the lane lifecycle.
  useShortcut("x", () => {
    const lane = lanes[focus.index];
    if (!lane) return;
    if (lane.status === "pending" || lane.status === "running") {
      void cancelTask(missionId, lane.taskId);
    } else {
      focus.unpin();
    }
  });

  const announceRef = useRef<HTMLDivElement>(null);
  useMissionAnnouncements(lanes, stream.events, announceRef, t);

  const swipeHandlers = useSwipeable({
    onSwipedLeft: () => focus.next(),
    onSwipedRight: () => focus.previous(),
    trackMouse: false,
  });

  const visibleLanes = useMemo<{ lane: TaskLane; realIndex: number }[]>(() => {
    if (!isMobile) return lanes.map((lane, i) => ({ lane, realIndex: i }));
    const focused = lanes[focus.index];
    return focused ? [{ lane: focused, realIndex: focus.index }] : [];
  }, [isMobile, lanes, focus.index]);

  if (lanes.length === 0) {
    return (
      <div className="flex flex-col gap-1.5 p-4">
        <AggregateHeader summary={summary} />
        <ConnectingChip label={t("mission", "connecting")} />
        <ul className="flex flex-col gap-1.5">
          {/* One placeholder skeleton until the first task_start lands. */}
          <LaneSkeleton />
        </ul>
        <div
          ref={announceRef}
          role="status"
          aria-live="polite"
          aria-label={t("mission", "ariaMissionRegion")}
          className="sr-only"
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5 p-4" {...(isMobile ? swipeHandlers : {})}>
      <AggregateHeader summary={summary} />
      {isMobile ? (
        <MobileLaneStrip lanes={lanes} focusIndex={focus.index} onSelect={focus.setIndex} />
      ) : null}
      <div
        ref={announceRef}
        role="status"
        aria-live="polite"
        aria-label={t("mission", "ariaMissionRegion")}
        className="sr-only"
      />
      <ul className="flex flex-col gap-1.5" aria-label={t("mission", "yourMissions")}>
        {visibleLanes.map(({ lane, realIndex }) => (
          <TaskLaneRow
            key={lane.taskId}
            lane={lane}
            missionId={missionId}
            isFocused={focus.index === realIndex}
            isPinned={focus.pinned.has(lane.taskId)}
            onFocus={() => focus.setIndex(realIndex)}
            onTogglePin={() => focus.togglePin(lane.taskId)}
          />
        ))}
      </ul>
    </div>
  );
}

function ConnectingChip({ label }: { label: string }) {
  return (
    <span
      role="status"
      className="inline-flex h-5 w-fit items-center gap-1 rounded border border-border/50 bg-muted/40 px-1.5 font-mono text-[11px] text-muted-foreground"
    >
      {label}
    </span>
  );
}

/**
 * Mobile strip — one small dot per lane plus a `{focused+1}/{total}`
 * counter, so the operator can see at a glance which lane is failing
 * even when only one lane is on screen.
 */
function MobileLaneStrip({
  lanes,
  focusIndex,
  onSelect,
}: {
  lanes: TaskLane[];
  focusIndex: number;
  onSelect: (i: number) => void;
}) {
  return (
    <div className="flex items-center gap-2 px-1 font-mono text-[11px] tabular-nums text-muted-foreground">
      <span>
        {focusIndex + 1}/{lanes.length}
      </span>
      <div className="flex items-center gap-1">
        {lanes.map((lane, i) => (
          <button
            key={lane.taskId}
            type="button"
            onClick={() => onSelect(i)}
            aria-label={lane.url}
            aria-current={i === focusIndex || undefined}
            className={cn(
              "h-2 w-2 rounded-full transition-transform",
              i === focusIndex && "scale-125 ring-1 ring-foreground/40",
              laneStatusDotClass(lane.status, { pulse: false }),
            )}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * Drives mission-level `aria-live="polite"` announcements:
 *
 *   - Mission start once `lanes.length` transitions from 0 → >0.
 *   - Lane terminal each time a new lane crosses into a terminal status.
 *   - Mission complete once every lane has terminated.
 *   - Mission failed when an SSE-stream-level `error` event with no
 *     `task_id` lands.
 *
 * Per-token announcements are deliberately not emitted; lane bodies set
 * `aria-live="off"` so a screen-reader user controls their own pace.
 */
function useMissionAnnouncements(
  lanes: TaskLane[],
  events: MissionStreamState["events"],
  announceRef: React.RefObject<HTMLDivElement | null>,
  t: ReturnType<typeof useT>,
): void {
  const announcedStart = useRef(false);
  const announcedTerminalIds = useRef<Set<string>>(new Set());
  const announcedComplete = useRef(false);
  const announcedMissionFailure = useRef<number | null>(null);

  const write = useCallback(
    (text: string) => {
      const node = announceRef.current;
      if (!node) return;
      node.textContent = text;
    },
    [announceRef],
  );

  useEffect(() => {
    if (!announcedStart.current && lanes.length > 0) {
      announcedStart.current = true;
      write(t("mission", "ariaMissionStarted", { count: lanes.length }));
    }
  }, [lanes.length, write, t]);

  useEffect(() => {
    let lastAnnouncement: string | null = null;
    for (const lane of lanes) {
      const isTerminal =
        lane.status === "succeeded" || lane.status === "failed" || lane.status === "cancelled";
      if (!isTerminal) continue;
      if (announcedTerminalIds.current.has(lane.taskId)) continue;
      announcedTerminalIds.current.add(lane.taskId);
      lastAnnouncement = t("mission", "ariaLaneTerminal", {
        url: lane.url || lane.taskId,
        status: lane.status,
      });
    }
    if (lastAnnouncement) write(lastAnnouncement);

    if (
      !announcedComplete.current &&
      lanes.length > 0 &&
      lanes.every((l) => l.status !== "pending" && l.status !== "running")
    ) {
      announcedComplete.current = true;
      const succeeded = lanes.filter((l) => l.status === "succeeded").length;
      write(t("mission", "ariaMissionComplete", { succeeded, total: lanes.length }));
    }
  }, [lanes, write, t]);

  useEffect(() => {
    for (const ev of events) {
      if (ev.type !== "error") continue;
      if (typeof ev.task_id === "string") continue;
      // `resume_lost` is an SSE-protocol signal — the per-mission ring
      // buffer evicted before this client reattached — not a mission
      // failure. The slide-over hydrates from the persisted detail
      // endpoint in that case, so announcing "Mission failed: buffer
      // evicted" here would lie to the screen reader. Skip the code
      // and trust the lane-terminal / mission-complete announcements
      // emitted from the hydrated state.
      const code = (ev as unknown as { content?: { code?: string } }).content?.code;
      if (code === "resume_lost") continue;
      if (announcedMissionFailure.current === ev.seq) return;
      announcedMissionFailure.current = ev.seq;
      write(t("mission", "ariaMissionFailed", { message: ev.content.message }));
      return;
    }
  }, [events, write, t]);
}
