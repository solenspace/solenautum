import type { NextRequest } from "next/server";

import { API_BASE, authorizationOr401 } from "@/shared/bff/upstream";

export const runtime = "nodejs";

export async function GET(_request: NextRequest, ctx: RouteContext<"/api/missions/[id]">) {
  const { id } = await ctx.params;
  const authorization = await authorizationOr401();
  if (authorization instanceof Response) return authorization;

  const upstream = await fetch(`${API_BASE}/missions/${id}`, {
    headers: { Authorization: authorization },
  });
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * Cancel a running mission (Spec 14). Forwards the DELETE to the api,
 * which routes the cancellation to the live `MissionRunner`. Idempotent:
 * a second DELETE on a terminal mission returns 204 with the current
 * status echoed in `x-mission-state` so the client can stop polling.
 */
export async function DELETE(_request: NextRequest, ctx: RouteContext<"/api/missions/[id]">) {
  const { id } = await ctx.params;
  const authorization = await authorizationOr401();
  if (authorization instanceof Response) return authorization;

  const upstream = await fetch(`${API_BASE}/missions/${id}`, {
    method: "DELETE",
    headers: { Authorization: authorization },
  });
  const headers: Record<string, string> = {};
  const missionState = upstream.headers.get("x-mission-state");
  if (missionState !== null) headers["x-mission-state"] = missionState;
  // Web Fetch spec: a Response with status 204 / 304 MUST NOT carry a
  // body — even an empty string trips `TypeError: Response constructor:
  // Invalid response status code 204`. Pass `null` for the body.
  const body = upstream.status === 204 ? null : await upstream.text();
  return new Response(body, { status: upstream.status, headers });
}
