"use client";

import { useEffect, useState } from "react";

import { useT } from "@/shared/i18n";

const _IDLE_THRESHOLD_MS = 5_000;
const _TAIL_CHARS = 80;

/**
 * Three-mode reasoning renderer. The "wall of text" problem at N=12 lanes
 * is the cognitive bottleneck this component solves:
 *
 *  - Focused lane → full text, no truncation. Operator wants to read.
 *  - Unfocused, < 5s since last token → tail (last 80 chars), one line.
 *    Operator can glance and feel that the lane is making progress.
 *  - Unfocused, ≥ 5s idle → "…thinking" chip. Operator stops reading
 *    a stalled lane that's still computing in the background.
 *
 * The 5s timer is driven by a 1s `setInterval` so the chip appears at
 * most 1s after the threshold trips. New tokens reset the timer
 * implicitly via `lastTokenAt`.
 */
export function ReasoningStream({
  text,
  isFocused,
  lastTokenAt,
}: {
  text: string;
  isFocused: boolean;
  lastTokenAt: number;
}) {
  const t = useT();
  const [now, setNow] = useState(() => Date.now());
  const idle = lastTokenAt > 0 && now - lastTokenAt > _IDLE_THRESHOLD_MS;

  useEffect(() => {
    if (isFocused || idle) return;
    // Once we cross the threshold the chip stays until a new token arrives,
    // which advances `lastTokenAt` and re-runs this effect.
    const id = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, [isFocused, idle]);

  if (text.length === 0) return null;

  if (isFocused) {
    return (
      <div className="border-l-2 border-border/50 pl-3 text-xs leading-relaxed text-muted-foreground/70 whitespace-pre-wrap break-words">
        {text}
      </div>
    );
  }

  if (idle) {
    return (
      <span
        title={t("mission", "loading")}
        className="inline-flex h-5 items-center gap-1 rounded border border-border/50 bg-muted/40 px-1.5 font-mono text-[11px] text-muted-foreground"
      >
        {t("mission", "thinking")}
      </span>
    );
  }

  const tail = text.slice(-_TAIL_CHARS);
  return (
    <div className="line-clamp-1 truncate border-l-2 border-border/50 pl-3 text-xs leading-relaxed text-muted-foreground/70">
      {tail}
    </div>
  );
}
