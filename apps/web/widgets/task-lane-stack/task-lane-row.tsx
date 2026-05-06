"use client";

import { ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { laneStatusDotClass, type TaskLane } from "@/features/run-mission";
import { useT } from "@/shared/i18n";
import { cn } from "@/shared/utils/cn";

import { InlineErrorChip } from "./inline-error-chip";
import { ReasoningStream } from "./reasoning-stream";
import { ResultPreview } from "./result-preview";
import { TierBadge } from "./tier-badge";
import { ToolChip } from "./tool-chip";

const _AUTO_COLLAPSE_DELAY_MS = 1_500;

interface TaskLaneRowProps {
  lane: TaskLane;
  isFocused: boolean;
  isPinned: boolean;
  onFocus: () => void;
}

/**
 * One row in the multi-lane stack. Expansion priority: focus → pin →
 * pending/running → failed/cancelled → succeeded-within-1.5s. The auto-
 * collapse window is driven by a single-shot `setTimeout` that flips
 * local state; no global timer subscription needed.
 */
export function TaskLaneRow({ lane, isFocused, isPinned, onFocus }: TaskLaneRowProps) {
  const t = useT();
  const ref = useRef<HTMLLIElement>(null);
  const [hasAutoCollapsed, setHasAutoCollapsed] = useState(false);

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

  const expanded = isExpanded(lane, isFocused, isPinned, hasAutoCollapsed);
  const hasError = lane.errorCode !== undefined;

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
      className={cn(
        "rounded-md border border-border/50 bg-card transition-colors",
        "data-[focused=true]:border-l-2 data-[focused=true]:border-primary data-[focused=true]:bg-accent/30",
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
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 text-muted-foreground transition-transform",
            !expanded && "-rotate-90",
          )}
          aria-hidden
        />
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
          {lane.toolCalls.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {lane.toolCalls.map((c) => (
                <ToolChip key={c.id} call={c} />
              ))}
            </div>
          ) : null}
          <ResultPreview preview={lane.preview} />
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
