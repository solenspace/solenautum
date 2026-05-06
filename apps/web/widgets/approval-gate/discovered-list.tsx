"use client";

import type { DiscoveredUrl } from "@/entities/mission/types";

import { ScorePill } from "./score-pill";

/**
 * Read-only streaming list rendered while the mission is in
 * `discovering` phase. Same row dimensions as the approval gate's
 * `UrlRow` so the transition between phases doesn't reflow. Rows
 * append as `url_discovered` events arrive.
 */
export function DiscoveredList({ urls }: { urls: DiscoveredUrl[] }) {
  return (
    <ul className="flex flex-col">
      {urls.map((u) => {
        let hostname = u.url;
        let pathPart = "";
        try {
          const parsed = new URL(u.url);
          hostname = parsed.hostname;
          pathPart = parsed.pathname + parsed.search;
        } catch {
          // Fall back to the raw URL.
        }
        return (
          <li
            key={u.url}
            className="grid h-7 grid-cols-[16px_auto_1fr_auto] items-center gap-2 border-b border-border/50 px-3"
          >
            {u.favicon_url ? (
              // eslint-disable-next-line @next/next/no-img-element — vendor favicons
              <img src={u.favicon_url} alt="" className="h-3 w-3 rounded-sm" />
            ) : (
              <span className="h-3 w-3" aria-hidden />
            )}
            <span className="font-mono text-[13px] text-foreground">{hostname}</span>
            <span className="truncate font-mono text-[13px] text-muted-foreground">{pathPart}</span>
            <ScorePill score={u.score} />
          </li>
        );
      })}
    </ul>
  );
}
