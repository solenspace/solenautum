import type { NextRequest } from "next/server";

import { API_BASE, authorizationOr401 } from "@/shared/bff/upstream";

export const runtime = "nodejs";

interface TaskRouteContext {
  params: Promise<{ id: string; taskId: string }>;
}

/**
 * Cancel one task within a still-running mission (Spec 14). Pending
 * tasks settle `cancelled` immediately; in-flight tasks finish their
 * current network egress before honoring the cancel.
 */
export async function DELETE(_request: NextRequest, ctx: TaskRouteContext) {
  const { id, taskId } = await ctx.params;
  const authorization = await authorizationOr401();
  if (authorization instanceof Response) return authorization;

  const upstream = await fetch(`${API_BASE}/missions/${id}/tasks/${taskId}`, {
    method: "DELETE",
    headers: { Authorization: authorization },
  });
  // Web Fetch spec: 204 responses must not carry a body (even ""), so
  // pass `null`. The upstream returns 204 on the happy path.
  const body = upstream.status === 204 ? null : await upstream.text();
  return new Response(body, { status: upstream.status });
}
