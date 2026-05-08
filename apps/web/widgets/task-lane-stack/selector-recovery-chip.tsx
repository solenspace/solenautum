"use client";

import { Sparkle } from "lucide-react";

import { useT } from "@/shared/i18n";

/**
 * Inline indicator for `selector_recovered` SSE events (Spec 13). Shows
 * how many times Scrapling's adaptive matcher rescued a saved selector
 * for this task's domain. Sentence-case copy via the i18n plural API;
 * tooltip explains the mechanism without occupying lane real estate.
 *
 * Visual parity with `ToolChip` — same height, border, background,
 * font-mono text — so the chip row scans uniformly.
 */
export function SelectorRecoveryChip({ count }: { count: number }) {
  const t = useT();
  return (
    <span
      className="inline-flex h-6 items-center gap-1.5 rounded border border-border/50 bg-muted/40 px-1.5 font-mono text-[11px] text-muted-foreground"
      title={t("mission", "selectorsRecoveredHint")}
    >
      <Sparkle className="h-3 w-3 text-primary" aria-hidden />
      <span>{t("mission", "selectorsRecovered", { count })}</span>
    </span>
  );
}
