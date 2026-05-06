import { auth } from "@clerk/nextjs/server";

/**
 * Shared BFF helpers for routes that proxy to the api. Centralizes the env
 * fallback, the Clerk JWT lookup, and the 401 short-circuit so the three
 * `/api/missions/*` routes stay thin.
 */
export const API_BASE = process.env.AUTUMN_API_URL ?? "http://localhost:8000";

/**
 * Returns the bearer header for the current Clerk session, or a 401
 * Response. Callers narrow with `if (header instanceof Response) return header`.
 */
export async function authorizationOr401(): Promise<string | Response> {
  const { getToken } = await auth();
  const token = await getToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  return `Bearer ${token}`;
}
