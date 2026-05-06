import type { NextRequest } from "next/server";

import { API_BASE, authorizationOr401 } from "@/shared/bff/upstream";

/**
 * SSE stream proxy. The web's `EventSource` cannot send custom headers, so
 * the consumer encodes its `Last-Event-ID` resume seq as `?after=<seq>` on
 * initial connect; on `EventSource` auto-reconnect the browser sends a real
 * `Last-Event-ID` header, which takes precedence over the (stale) mount-time
 * query param. The response body is the upstream `ReadableStream` passed
 * through verbatim — buffering would defeat the purpose of streaming.
 *
 * `request.signal` propagates client disconnects to the upstream `fetch`
 * so the api-side consumer tears down immediately rather than waiting for
 * the 60s eviction grace.
 *
 * `runtime = "nodejs"` is required because the Edge runtime caps long-lived
 * streams; SSE missions outlive a single request-response cycle.
 */
export const runtime = "nodejs";

export async function GET(request: NextRequest, ctx: RouteContext<"/api/missions/[id]/stream">) {
  const { id } = await ctx.params;
  const authorization = await authorizationOr401();
  if (authorization instanceof Response) return authorization;

  const browserSeq = request.headers.get("last-event-id");
  const querySeq = new URL(request.url).searchParams.get("after");
  const lastEventId = browserSeq ?? querySeq;

  const headers: Record<string, string> = { Authorization: authorization };
  if (lastEventId !== null) headers["Last-Event-ID"] = lastEventId;

  const upstream = await fetch(`${API_BASE}/run-mission/${id}/stream`, {
    headers,
    signal: request.signal,
  });
  if (!upstream.ok || upstream.body === null) {
    return new Response(`upstream error: ${upstream.status}`, { status: upstream.status });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
