"use client";

import { useEffect, useMemo } from "react";

import type { DiscoveredUrl } from "@/entities/mission/types";

/**
 * Horizontal chip strip listing each unique domain in `urls` with its
 * count. Clicking a chip filters the parent list; clicking the active
 * chip again (or pressing Esc) clears the filter.
 *
 * Each chip is `h-5` (20px) per the spec's density rules so the strip
 * doesn't dominate the slide-over header. Sorted by count desc so the
 * most-represented sources surface first.
 */
export function DomainFilterStrip({
  urls,
  active,
  onChange,
}: {
  urls: DiscoveredUrl[];
  active: string | null;
  onChange: (next: string | null) => void;
}) {
  const groups = useMemo(() => {
    const counts = new Map<string, number>();
    for (const u of urls) {
      let host = "";
      try {
        host = new URL(u.url).hostname;
      } catch {
        host = u.url;
      }
      counts.set(host, (counts.get(host) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [urls]);

  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && active !== null) onChange(null);
    }
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [active, onChange]);

  if (groups.length <= 1) return null;

  return (
    <div className="flex flex-wrap gap-1 px-3 py-2">
      {groups.map(([domain, count]) => (
        <button
          key={domain}
          type="button"
          data-active={active === domain}
          onClick={() => onChange(active === domain ? null : domain)}
          className="inline-flex h-5 items-center gap-1 rounded border border-border/40 bg-muted/40 px-1.5 font-mono text-[11px] tabular-nums text-muted-foreground hover:bg-muted/70 data-[active=true]:border-foreground/40 data-[active=true]:bg-muted data-[active=true]:text-foreground"
        >
          {domain}
          <span className="text-muted-foreground/60">({count})</span>
        </button>
      ))}
    </div>
  );
}
