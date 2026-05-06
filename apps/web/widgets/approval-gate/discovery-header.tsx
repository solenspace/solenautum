"use client";

import { useT } from "@/shared/i18n";

/**
 * Header strip above the discovery list. While discovery streams,
 * renders a pulsing "Searching… {count} found" chip; once the agent
 * finalizes (`discovery_complete`), switches to "{count} URLs found".
 * The slide-over uses this same component for both states; the
 * `streaming` prop drives the pulsing dot.
 */
export function DiscoveryHeader({ count, streaming }: { count: number; streaming: boolean }) {
  const t = useT();
  const label = streaming
    ? t("mission", "searching", { count })
    : t("mission", "discoveryComplete", { count });
  return (
    <div className="flex h-7 items-center gap-2 px-3 font-mono text-[11px] tabular-nums text-muted-foreground">
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          streaming ? "animate-pulse bg-primary" : "bg-state-success"
        }`}
        aria-hidden
      />
      {label}
    </div>
  );
}
