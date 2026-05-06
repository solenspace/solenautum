import type { NextRequest } from "next/server";

import { API_BASE, authorizationOr401 } from "@/shared/bff/upstream";

/**
 * BFF proxy for `POST /missions/{id}/approve`. Forwards the user's
 * approved URL list verbatim to the api; the api enforces ownership
 * (RLS), phase (`AWAITING_APPROVAL`), SSRF, and the in-memory
 * approval-registry handoff.
 *
 * `runtime = "nodejs"` matches the SSE proxy — Edge can't accommodate
 * the long-poll-style flows this approval gate participates in.
 */
export const runtime = "nodejs";

export async function POST(request: NextRequest, ctx: RouteContext<"/api/missions/[id]/approve">) {
  const { id } = await ctx.params;
  const authorization = await authorizationOr401();
  if (authorization instanceof Response) return authorization;

  const body = await request.text();
  const upstream = await fetch(`${API_BASE}/missions/${id}/approve`, {
    method: "POST",
    headers: { Authorization: authorization, "Content-Type": "application/json" },
    body,
  });
  // 204 No Content → empty body; otherwise relay the upstream JSON detail.
  const text = upstream.status === 204 ? "" : await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: text ? { "Content-Type": "application/json" } : {},
  });
}
