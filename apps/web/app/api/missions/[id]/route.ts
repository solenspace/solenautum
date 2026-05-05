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
