"use client";

import type { SseEvent } from "@autumn/sse-protocol";
import { useMemo } from "react";

import type { DiscoveredUrl } from "@/entities/mission/types";

/**
 * Reduces `url_discovered` SSE events to a deduplicated `DiscoveredUrl[]`
 * preserving arrival order. The SSE schema (Spec 06) carries only `url`,
 * `source`, and `score`; `favicon_url` and `title` come from the
 * persisted `discovered_urls` jsonb column on slide-over reattach (via
 * `GET /api/missions/{id}`). The optional `seedFromRow` arg lets callers
 * preload that persisted list before the live stream starts emitting.
 */
export function useDiscoveredUrls(
  events: SseEvent[],
  seedFromRow: DiscoveredUrl[] | null = null,
): DiscoveredUrl[] {
  return useMemo(() => {
    const byUrl = new Map<string, DiscoveredUrl>();
    if (seedFromRow) {
      for (const u of seedFromRow) byUrl.set(u.url, u);
    }
    for (const event of events) {
      if (event.type !== "url_discovered") continue;
      const { url, source, score } = event.content;
      if (byUrl.has(url)) continue;
      byUrl.set(url, {
        url,
        score: score ?? 0,
        source,
        favicon_url: null,
        title: null,
      });
    }
    return Array.from(byUrl.values());
  }, [events, seedFromRow]);
}
