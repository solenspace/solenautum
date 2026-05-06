"use client";

import { ChevronRight } from "lucide-react";
import { useState } from "react";

import type { ToolCall } from "@/features/run-mission";
import { cn } from "@/shared/utils/cn";

/**
 * Single tool-call chip with click-to-expand inline body. The status dot
 * mirrors the `ok` field — neutral while running, green on success, red on
 * failure. Expanded body shows args + summary in a bounded mono block;
 * `max-h-32` plus internal scroll keeps an oversized payload from
 * stretching the lane.
 */
export function ToolChip({ call }: { call: ToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const dotCls =
    call.ok === true
      ? "bg-state-success"
      : call.ok === false
        ? "bg-state-error"
        : "bg-primary animate-pulse";

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className={cn(
          "inline-flex h-6 items-center gap-1.5 rounded border border-border/50 bg-muted/40 px-1.5",
          "font-mono text-[11px] text-foreground transition-colors hover:bg-muted/60",
        )}
      >
        <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", dotCls)} aria-hidden />
        <span>{call.toolName}</span>
        {call.durationMs !== undefined ? (
          <span className="text-muted-foreground tabular-nums">
            · {(call.durationMs / 1000).toFixed(1)}s
          </span>
        ) : null}
        <ChevronRight
          className={cn(
            "h-3 w-3 text-muted-foreground transition-transform",
            expanded && "rotate-90",
          )}
          aria-hidden
        />
      </button>
      {expanded ? (
        <div className="max-h-32 overflow-auto rounded-md border border-border/50 bg-card p-2 font-mono text-[11px] leading-relaxed">
          {call.args ? (
            <pre className="whitespace-pre-wrap break-words">
              {JSON.stringify(call.args, null, 2)}
            </pre>
          ) : null}
          {call.summary ? <p className="mt-2 text-muted-foreground">{call.summary}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
