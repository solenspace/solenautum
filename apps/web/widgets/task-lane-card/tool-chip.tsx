"use client";

import { useState } from "react";

import { cn } from "@/shared/utils/cn";

export interface ToolCall {
  id: string;
  toolName: string;
  args?: Record<string, unknown>;
  durationMs?: number;
  ok?: boolean;
  summary?: string;
}

/**
 * Tool-call chip — collapsed by default to one row of metadata; expands to
 * reveal args + summary when clicked. The status dot mirrors task status:
 * green for `ok`, red for failure, neutral when still running.
 */
export function ToolChip({ call }: { call: ToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const dotColor =
    call.ok === undefined
      ? "bg-muted-foreground/60"
      : call.ok
        ? "bg-state-success"
        : "bg-state-error";

  return (
    <button
      type="button"
      onClick={() => setExpanded((value) => !value)}
      className={cn(
        "group inline-flex max-w-full flex-col items-stretch gap-1 rounded border border-border/50 bg-muted/40 px-1.5 py-1 text-left transition-colors hover:bg-muted/60",
        expanded && "max-w-[28rem]",
      )}
      aria-expanded={expanded}
    >
      <span className="inline-flex h-4 items-center gap-1.5 font-mono text-[11px]">
        <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", dotColor)} />
        <span className="text-foreground">{call.toolName}</span>
        {call.durationMs !== undefined ? (
          <span className="text-muted-foreground tabular-nums">
            · {(call.durationMs / 1000).toFixed(1)}s
          </span>
        ) : null}
      </span>
      {expanded ? (
        <div className="flex flex-col gap-1 pt-1 font-mono text-[11px] text-muted-foreground">
          {call.args ? (
            <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words text-[11px]">
              {JSON.stringify(call.args, null, 2)}
            </pre>
          ) : null}
          {call.summary ? <span className="text-foreground">{call.summary}</span> : null}
        </div>
      ) : null}
    </button>
  );
}
