"use client";

import { ChevronDown, Pin } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { laneStatusDotClass, type TaskLane } from "@/features/run-mission";
import { useT } from "@/shared/i18n";
import { cn } from "@/shared/utils/cn";

import { InlineErrorChip } from "./inline-error-chip";
import { ReasoningStream } from "./reasoning-stream";
import { ResultPreview } from "./result-preview";
import { SelectorRecoveryChip } from "./selector-recovery-chip";
import { TierBadge } from "./tier-badge";
import { ToolChip } from "./tool-chip";

const _AUTO_COLLAPSE_DELAY_MS = 1_500;

interface TaskLaneRowProps {
  lane: TaskLane;
  /** Owning mission id — needed for the snapshot download href and any
   * future per-task BFF call that originates inside the row. */
  missionId: string;
  isFocused: boolean;
  isPinned: boolean;
  onFocus: () => void;
  /** Toggle this lane's pinned state. Spec 14 moved the pin/unpin
   * keyboard shortcut off `X` (now state-aware cancel-or-unpin) onto a
   * small icon button on the row. */
  onTogglePin: () => void;
}

/**
 * One row in the multi-lane stack. Expansion priority:
 *
 *   user toggle (chevron) → focus → pin → pending/running → failed/
 *   cancelled → succeeded-within-1.5s.
 *
 * The auto-collapse window is driven by a single-shot `setTimeout`
 * that flips local state; no global timer subscription needed. The
 * chevron is a real button (separate from pin) so users can hide a
 * verbose lane without committing to the "pin keeps it open" semantic.
 */
export function TaskLaneRow({
  lane,
  missionId,
  isFocused,
  isPinned,
  onFocus,
  onTogglePin,
}: TaskLaneRowProps) {
  const t = useT();
  const ref = useRef<HTMLLIElement>(null);
  const [hasAutoCollapsed, setHasAutoCollapsed] = useState(false);
  // null = follow defaults; true/false = user explicitly toggled the
  // chevron and that overrides the heuristic until they toggle again.
  const [userExpanded, setUserExpanded] = useState<boolean | null>(null);

  useEffect(() => {
    if (lane.status !== "succeeded" || lane.finishedAt === undefined) return;
    const remaining = _AUTO_COLLAPSE_DELAY_MS - (Date.now() - lane.finishedAt);
    if (remaining <= 0) {
      setHasAutoCollapsed(true);
      return;
    }
    const id = window.setTimeout(() => setHasAutoCollapsed(true), remaining);
    return () => window.clearTimeout(id);
  }, [lane.status, lane.finishedAt]);

  useEffect(() => {
    if (isFocused && ref.current) {
      ref.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [isFocused]);

  const expanded = userExpanded ?? isExpanded(lane, isFocused, isPinned, hasAutoCollapsed);
  const hasError = lane.errorCode !== undefined;
  const hasPreview = typeof lane.preview === "string" && lane.preview.trim().length > 0;
  const hasReasoning = lane.reasoningTokens.length > 0;
  const hasToolChips = lane.toolCalls.length > 0 || (lane.selectorRecoveryCount ?? 0) > 0;
  const isTerminal = lane.status !== "pending" && lane.status !== "running";
  const showFailedFallback =
    expanded &&
    isTerminal &&
    lane.status !== "succeeded" &&
    !hasError &&
    !hasPreview &&
    !hasReasoning &&
    !hasToolChips;

  return (
    <li
      ref={ref}
      data-focused={isFocused}
      data-status={lane.status}
      data-user-expanded={isPinned}
      data-expanded={expanded}
      aria-current={isFocused || undefined}
      onClick={onFocus}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onFocus();
        }
      }}
      tabIndex={isFocused ? 0 : -1}
      data-pinned={isPinned}
      className={cn(
        "rounded-md border border-border/50 bg-card transition-colors",
        "data-[focused=true]:border-l-2 data-[focused=true]:border-primary data-[focused=true]:bg-accent/30",
        // Pinned lanes get a clearly distinguishable accent ring so the
        // user can spot them at a glance even when scrolled past the
        // active row. The ring is subtle enough to coexist with the
        // focus border on a focused-and-pinned lane.
        "data-[pinned=true]:ring-1 data-[pinned=true]:ring-primary/40",
      )}
    >
      <div className="flex h-8 items-center gap-2 px-2 text-[13px]">
        <span
          className={cn("h-1.5 w-1.5 shrink-0 rounded-full", laneStatusDotClass(lane.status))}
          aria-hidden
        />
        <TierBadge tier={lane.tier} />
        <span className="flex-1 truncate font-mono text-[13px] text-foreground">
          {lane.url || t("mission", "loading")}
        </span>
        {lane.latencyMs !== undefined ? (
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
            {(lane.latencyMs / 1000).toFixed(1)}s
          </span>
        ) : null}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onTogglePin();
          }}
          aria-label={isPinned ? t("mission", "unpin") : t("mission", "pin")}
          aria-pressed={isPinned}
          title={isPinned ? t("mission", "unpin") : t("mission", "pin")}
          className={cn(
            "flex h-6 w-6 items-center justify-center rounded-md transition-colors",
            isPinned
              ? "bg-primary/15 text-primary hover:bg-primary/25"
              : "text-muted-foreground hover:bg-accent/40 hover:text-foreground",
          )}
        >
          <Pin
            className={cn(
              "h-3.5 w-3.5 transition-transform",
              isPinned ? "rotate-45 fill-primary" : "fill-none",
            )}
            aria-hidden
          />
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setUserExpanded(!expanded);
          }}
          aria-label={expanded ? t("mission", "collapse") : t("mission", "expand")}
          aria-expanded={expanded}
          className="text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronDown
            className={cn("h-3.5 w-3.5 transition-transform", !expanded && "-rotate-90")}
            aria-hidden
          />
        </button>
      </div>

      {expanded ? (
        <div
          role="log"
          aria-live="off"
          className="flex flex-col gap-3 px-2 pb-3"
          style={{ contentVisibility: "auto", containIntrinsicSize: "200px" }}
        >
          {hasError && lane.errorCode !== undefined ? (
            <InlineErrorChip code={lane.errorCode} message={lane.errorMessage ?? ""} />
          ) : null}
          <ReasoningStream
            text={lane.reasoningTokens}
            isFocused={isFocused}
            lastTokenAt={lane.lastTokenAt}
          />
          {lane.toolCalls.length > 0 || (lane.selectorRecoveryCount ?? 0) > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {lane.toolCalls.map((c) => (
                <ToolChip key={c.id} call={c} />
              ))}
              {lane.selectorRecoveryCount && lane.selectorRecoveryCount > 0 ? (
                <SelectorRecoveryChip count={lane.selectorRecoveryCount} />
              ) : null}
            </div>
          ) : null}
          <ResultPreview
            preview={lane.preview}
            missionId={missionId}
            taskId={lane.taskId}
            snapshotKey={lane.snapshotKey}
          />
          {showFailedFallback ? (
            <span className="text-[11px] text-muted-foreground">
              {t("mission", `lane_terminal_${lane.status}` as const)}
            </span>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function isExpanded(
  lane: TaskLane,
  isFocused: boolean,
  isPinned: boolean,
  hasAutoCollapsed: boolean,
): boolean {
  if (isFocused || isPinned) return true;
  const isTerminal = lane.status !== "pending" && lane.status !== "running";
  if (!isTerminal) return true;
  if (lane.status !== "succeeded") return true;
  return !hasAutoCollapsed;
}
