import type { NextRequest } from "next/server";

import { API_BASE, authorizationOr401 } from "@/shared/bff/upstream";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  const authorization = await authorizationOr401();
  if (authorization instanceof Response) return authorization;

  const body = await request.text();
  const upstream = await fetch(`${API_BASE}/missions`, {
    method: "POST",
    headers: { Authorization: authorization, "Content-Type": "application/json" },
    body,
  });
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function GET() {
  const authorization = await authorizationOr401();
  if (authorization instanceof Response) return authorization;

  const upstream = await fetch(`${API_BASE}/missions`, {
    headers: { Authorization: authorization },
  });
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
