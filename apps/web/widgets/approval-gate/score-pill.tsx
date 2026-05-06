"use client";

/**
 * Inline score badge with a colored leading dot. Bands per Spec 12:
 *   * `>= 0.8` → success
 *   * `>= 0.5` → warn
 *   * `< 0.5`  → muted
 *
 * The pill itself is monochrome; only the dot carries color so the score
 * stays readable on hover/checked row backgrounds.
 */
export function ScorePill({ score }: { score: number }) {
  const band =
    score >= 0.8 ? "bg-state-success" : score >= 0.5 ? "bg-state-warn" : "bg-muted-foreground/40";
  return (
    <span className="inline-flex h-5 items-center gap-1 rounded px-1.5 font-mono text-[11px] tabular-nums">
      <span className={`h-1.5 w-1.5 rounded-full ${band}`} aria-hidden />
      {score.toFixed(2)}
    </span>
  );
}
