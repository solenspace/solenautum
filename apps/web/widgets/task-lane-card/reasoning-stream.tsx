"use client";

import type { SseEvent } from "@autumn/sse-protocol";
import { useEffect, useRef, useState } from "react";

const _BATCH_SIZE = 5;

/**
 * Renders streamed `token` events as a dim, left-bordered block.
 *
 * Per-token transitions read flashy on dense UIs (`ui-context.md`), so the
 * full token stream is computed from the events array but the DOM is only
 * flushed once a `requestAnimationFrame` boundary is hit AND the unflushed
 * tail is at least `_BATCH_SIZE` characters. Italic is intentionally
 * avoided — Geist's display weight reads off when italic at 12px.
 */
export function ReasoningStream({ tokens }: { tokens: SseEvent[] }) {
  const fullText = _joinTokens(tokens);
  const [rendered, setRendered] = useState("");
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const tail = fullText.slice(rendered.length);
    if (tail.length === 0) return;
    if (tail.length < _BATCH_SIZE && rafRef.current === null) {
      // Hold the tail until either the batch fills or one more token arrives.
      return;
    }
    if (rafRef.current !== null) return;
    rafRef.current = window.requestAnimationFrame(() => {
      rafRef.current = null;
      setRendered(fullText);
    });
  }, [fullText, rendered]);

  useEffect(
    () => () => {
      if (rafRef.current !== null) {
        window.cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    },
    [],
  );

  if (fullText.length === 0) return null;
  return (
    <div className="border-l-2 border-border/50 pl-3 text-xs leading-relaxed text-muted-foreground/70 transition-opacity duration-[60ms]">
      {rendered || fullText}
    </div>
  );
}

function _joinTokens(events: readonly SseEvent[]): string {
  let out = "";
  for (const event of events) {
    if (event.type === "token") out += event.content;
  }
  return out;
}
