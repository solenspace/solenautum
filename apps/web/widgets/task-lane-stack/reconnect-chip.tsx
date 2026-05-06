"use client";

import { Loader2 } from "lucide-react";

import { useT } from "@/shared/i18n";

/**
 * Inline `Reconnecting…` chip surfaced in the aggregate header when the
 * SSE stream's `EventSource` fires `error`. The browser's native auto-
 * reconnect handles the retry; this chip exists only so the operator
 * sees a transient indicator. Banner-promotion-after-10s is deferred to
 * Spec 15.
 */
export function ReconnectChip() {
  const t = useT();
  return (
    <span
      role="status"
      className="inline-flex h-5 items-center gap-1 rounded border border-border/50 bg-muted/40 px-1.5 font-mono text-[11px] text-muted-foreground"
    >
      <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
      {t("mission", "reconnecting")}
    </span>
  );
}
