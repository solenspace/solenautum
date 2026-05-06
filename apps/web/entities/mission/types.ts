/**
 * Mission status values mirror the api's `Status` StrEnum (in
 * `apps/api/app/persistence/models.py`). Kept literal so the sidebar's
 * group enumeration stays exhaustive at the type level.
 */
export type MissionStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled";

export type MissionMode = "url" | "description";

/**
 * Description-mode workflow position. URL-mode missions move
 * `null → scraping → done`; description-mode walks the full chain.
 * Mirrors the api's `MissionPhase` StrEnum.
 */
export type MissionPhase = "discovering" | "awaiting_approval" | "scraping" | "done";

/**
 * One Tavily-supplied URL surfaced to the approval gate. Matches the
 * `DiscoveredUrl` pydantic model on the api side; arrives via
 * `GET /api/missions/{id}` (jsonb column) on slide-over reattach. The
 * SSE `url_discovered` event carries only `url`/`source`/`score`, so
 * `favicon_url` and `title` come from the persisted row.
 */
export interface DiscoveredUrl {
  url: string;
  score: number;
  source: string;
  favicon_url: string | null;
  title: string | null;
}

/**
 * The JSON projection returned by `GET /api/missions` and
 * `GET /api/missions/{id}`. Matches the `_MissionResponse` pydantic model on
 * the api side. Timestamps arrive as ISO 8601 strings; the UI parses on
 * demand because `Date` round-trips lose precision through JSON.
 */
export interface MissionRow {
  id: string;
  prompt: string;
  mode: MissionMode;
  status: MissionStatus;
  cost_cents: number;
  created_at: string;
  finished_at: string | null;
  phase?: MissionPhase | null;
  skip_approval?: boolean;
  discovered_urls?: DiscoveredUrl[] | null;
  approved_urls?: string[] | null;
}
