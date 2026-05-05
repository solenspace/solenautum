/**
 * Mission status values mirror the api's `Status` StrEnum (in
 * `apps/api/app/persistence/models.py`). Kept literal so the sidebar's
 * group enumeration stays exhaustive at the type level.
 */
export type MissionStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled";

export type MissionMode = "url" | "description";

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
}
