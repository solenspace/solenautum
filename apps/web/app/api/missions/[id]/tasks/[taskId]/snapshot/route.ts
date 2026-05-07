import type { NextRequest } from "next/server";

import { API_BASE, authorizationOr401 } from "@/shared/bff/upstream";

export const runtime = "nodejs";

interface SnapshotRouteContext {
  params: Promise<{ id: string; taskId: string }>;
}

/**
 * Snapshot redirect proxy (Spec 14). The api returns a 302 with a
 * 1-hour signed R2 URL in `Location`. We use `redirect: "manual"` so
 * the BFF does NOT follow that redirect itself — letting fetch follow
 * it would stream the gzipped HTML through this edge unnecessarily and
 * (worse) attach our Authorization header to the R2 hop, leaking the
 * Clerk JWT to a third-party host. Instead we relay the 302 to the
 * browser; the browser then navigates directly to the signed URL.
 */
export async function GET(_request: NextRequest, ctx: SnapshotRouteContext) {
  const { id, taskId } = await ctx.params;
  const authorization = await authorizationOr401();
  if (authorization instanceof Response) return authorization;

  const upstream = await fetch(`${API_BASE}/missions/${id}/tasks/${taskId}/snapshot`, {
    headers: { Authorization: authorization },
    redirect: "manual",
  });
  const location = upstream.headers.get("location");
  if (upstream.status === 302 && location !== null) {
    return new Response(null, { status: 302, headers: { Location: location } });
  }
  // 404, 401, 5xx — relay verbatim.
  const text = await upstream.text().catch(() => "");
  return new Response(text, { status: upstream.status });
}
