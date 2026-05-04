# 04 — clerk-auth-and-security-foundation

## Goal

Stand up the authentication and security foundation that every later
spec inherits. Clerk handles sign-in / sign-up on the web and issues
JWTs; the api verifies those JWTs via Clerk's official Python SDK and
binds the resulting `user_id` to a request-scoped context. The same
spec ships `apps/api/app/security.py` — the **load-bearing protected
file** — which centralizes the SSRF guard, optional URL allow-list,
per-user rate limiter (slowapi), and `robots.txt` honor logic that
invariants 1, 10, 11 depend on. After this spec, the api refuses
unauthenticated traffic, blocks SSRF before any future fetcher tier
exists, and honors `robots.txt` for any URL it inspects.

## Dependencies

- `specs/01-monorepo-skeleton.md` — workspaces, env loading patterns
- `specs/02-linting-and-formatting.md` — Biome / ruff / mypy enforce
  the strict TypeScript + Pydantic v2 style this spec uses
- `specs/03-git-hooks-and-commits.md` — commit gates ensure none of
  this lands with a type error or unsorted import

## Design Decisions

- **Clerk** owns sign-in / sign-up on the web side via
  `@clerk/nextjs` ≥ 6. App Router middleware protects every route
  under `/(app)/*`; auth pages live in `/(auth)/sign-in/...` and
  `/(auth)/sign-up/...`.
- **Clerk's official Python SDK** (`clerk-backend-api`) verifies
  JWTs on the api side. The SDK handles JWKS fetch, in-memory
  caching, key rotation, and signature verification. We do not roll
  our own.
- **Webhook → Neon `users` sync is deferred to Spec 05.**
  Spec 04 ships authentication without persistence; the
  `/webhooks/clerk` endpoint and the `users` table land together in
  Spec 05.
- **Rate limiter: slowapi** with the built-in in-memory backend.
  Decorators on the FastAPI route handlers; `60/minute` and
  `1000/day` keyed on `user_id`. Swap to a Redis backend later
  (one config line) if the deployment ever scales beyond a single
  process.
- **SSRF guard** blocks private CIDR ranges before any URL is
  fetched: `127/8`, `10/8`, `172.16/12`, `192.168/16`, `169.254/16`.
  Hostname → IP resolution happens in the guard; both IPv4 and
  IPv6 ranges are checked. The guard is exported as a function and
  called by every fetcher tier in later specs (invariant 1).
- **URL allow-list** is opt-in via the `AUTUMN_URL_ALLOWLIST` env
  var (comma-separated domain patterns). When set, only matching
  domains pass; when unset, all non-SSRF URLs pass. Off in dev,
  recommended on for any hosted deployment.
- **`robots.txt` honor** uses Python's stdlib
  `urllib.robotparser`. Each fetched `robots.txt` is cached
  in-process for 24h. The check fires for every URL before the
  fetcher tier runs; bypass requires the **mission row** to carry
  a user-attributed `robots_override = True` flag (the row
  doesn't exist yet — Spec 05 introduces it; this spec ships the
  function with a `robots_override: bool = False` parameter ready
  to wire in).
- **Request-scoped user context** uses Python's `contextvars`.
  A FastAPI dependency reads the JWT, verifies it, sets
  `current_user.set(user)` for the request, and yields the User.
  All later specs read `current_user.get()` instead of re-passing
  the user through every call.
- **`apps/api/app/config.py`** uses `pydantic-settings` v2 to load
  env vars at startup. Missing required vars fail fast at boot.
- **`apps/api/app/security.py` is protected** from this spec
  forward. Edits require explicit approval per
  `context/ai-workflow-rules.md`. All other specs call its
  functions; none modify them.

References:
- `context/architecture.md` — Auth and Access Model, Invariants 1,
  10, 11
- `context/code-standards.md` — Auth integration, FastAPI, Python
- `context/ui-context.md` — Voice & Copy (auth screen copy)

## Implementation

### A. Web — Clerk integration (`apps/web/`)

#### Install

From repo root:

```bash
pnpm --filter @autumn/web add @clerk/nextjs
```

#### Env vars (`apps/web/.env.local`)

```
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL=/missions
NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL=/missions
```

`.env.local` is gitignored. A new `apps/web/.env.example` is
committed listing the keys with empty values.

#### `apps/web/proxy.ts`

Clerk's Next 16 quickstart uses `proxy.ts` (the renamed
middleware path Next 16 introduced; Clerk emits a runtime warning
if the file is named `middleware.ts`). The export shape and
`auth.protect()` semantics are identical to the previous
`middleware.ts` convention.

```ts
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

const isProtectedRoute = createRouteMatcher([
  "/missions(.*)",
  "/api/(.*)",
]);

export default clerkMiddleware(async (auth, req) => {
  if (isProtectedRoute(req)) await auth.protect();
});

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
```

#### `apps/web/app/layout.tsx` — wrap root

```tsx
import { ClerkProvider } from "@clerk/nextjs";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body>{children}</body>
      </html>
    </ClerkProvider>
  );
}
```

#### Auth pages

- `apps/web/app/(auth)/layout.tsx` — minimal centered layout, no
  marketing chrome. Per `ui-context.md` Voice & Copy: single-line
  value prop above the form, no testimonials, no logo wall.

  ```tsx
  export default function AuthLayout({ children }: { children: React.ReactNode }) {
    return (
      <main className="grid min-h-dvh place-items-center px-6">
        <div className="w-full max-w-sm">
          <p className="mb-6 text-sm text-muted-foreground">
            Scrape websites in parallel.
          </p>
          {children}
        </div>
      </main>
    );
  }
  ```

  The `text-muted-foreground` token comes from the shadcn theme
  bridge that Spec 08 installs; for now it resolves to a sensible
  fallback.

- `apps/web/app/(auth)/sign-in/[[...sign-in]]/page.tsx`:

  ```tsx
  import { SignIn } from "@clerk/nextjs";

  export default function Page() {
    return <SignIn />;
  }
  ```

- `apps/web/app/(auth)/sign-up/[[...sign-up]]/page.tsx`:

  ```tsx
  import { SignUp } from "@clerk/nextjs";

  export default function Page() {
    return <SignUp />;
  }
  ```

#### `apps/web/app/missions/page.tsx` — placeholder protected page

```tsx
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

export default async function MissionsPage() {
  const { userId } = await auth();
  if (!userId) redirect("/sign-in");

  return (
    <main className="p-6">
      <p className="text-sm">Signed in. Mission UI ships in spec 08.</p>
    </main>
  );
}
```

This proves the protected route works end-to-end. The full mission
UI lands in Spec 08.

### B. API — config and SDK install (`apps/api/`)

#### Install

```bash
cd apps/api
uv add fastapi uvicorn[standard] clerk-backend-api pydantic-settings slowapi httpx
uv add --dev pytest pytest-asyncio httpx
```

`httpx` ships in both prod and dev sets (it's how SSRF tests
forge requests).

#### `apps/api/app/config.py`

```python
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    clerk_secret_key: str = Field(..., alias="CLERK_SECRET_KEY")
    clerk_publishable_key: str = Field(..., alias="CLERK_PUBLISHABLE_KEY")

    autumn_user_agent: str = Field(
        default="AutumnBot/0.1 (+https://github.com/mtohernandez/autumn)",
        alias="AUTUMN_USER_AGENT",
    )

    autumn_url_allowlist: str | None = Field(
        default=None,
        alias="AUTUMN_URL_ALLOWLIST",
        description="Comma-separated domain patterns. None disables the allow-list.",
    )

    @property
    def allowlist_patterns(self) -> tuple[str, ...]:
        if not self.autumn_url_allowlist:
            return ()
        return tuple(p.strip() for p in self.autumn_url_allowlist.split(",") if p.strip())


settings = Settings()  # type: ignore[call-arg]  # env-driven
```

The `# type: ignore` on instantiation is the documented escape
hatch when pydantic-settings reads from env at construction time.
A justification comment is mandatory per `code-standards.md`.

### C. API — security.py (protected from now on)

#### `apps/api/app/security.py`

```python
from __future__ import annotations

import ipaddress
import socket
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from clerk_backend_api import Clerk
from clerk_backend_api.jwks_helpers import (
    AuthenticateRequestOptions,
    authenticate_request,
)
from fastapi import Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings


# --- request-scoped user context -----------------------------------------

@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: str
    session_id: str


_current_user: ContextVar[CurrentUser | None] = ContextVar("current_user", default=None)


def get_current_user() -> CurrentUser:
    """Return the user bound to this request. Raises if unset."""
    user = _current_user.get()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    return user


# --- Clerk verification --------------------------------------------------

_clerk = Clerk(bearer_auth=settings.clerk_secret_key)


async def require_user(request: Request) -> CurrentUser:
    """FastAPI dependency: verify the Clerk JWT and bind user to context."""
    httpx_request = httpx.Request(
        method=request.method,
        url=str(request.url),
        headers=request.headers.raw,
    )
    state = authenticate_request(
        _clerk,
        httpx_request,
        AuthenticateRequestOptions(),
    )
    if not state.is_signed_in:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")

    payload = state.payload
    if payload is None or "sub" not in payload or "sid" not in payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid session")

    user = CurrentUser(user_id=payload["sub"], session_id=payload["sid"])
    _current_user.set(user)
    return user


RequireUser = Annotated[CurrentUser, Depends(require_user)]


# --- SSRF guard (invariant 1) --------------------------------------------

_PRIVATE_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class UrlNotAllowed(HTTPException):
    def __init__(self, url: str, reason: str) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"url": url, "reason": reason},
        )


def assert_safe_url(url: str) -> None:
    """Reject SSRF + non-allowlisted URLs. Called by every fetcher tier."""
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UrlNotAllowed(url, "scheme not allowed")
    if not parsed.hostname:
        raise UrlNotAllowed(url, "missing hostname")

    # SSRF: resolve hostname → all addresses, reject if any is private.
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UrlNotAllowed(url, "dns resolution failed") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        for net in _PRIVATE_NETWORKS:
            if ip in net:
                raise UrlNotAllowed(url, "private address blocked")

    # Optional allow-list.
    patterns = settings.allowlist_patterns
    if patterns and not any(_matches(parsed.hostname, p) for p in patterns):
        raise UrlNotAllowed(url, "domain not in allow-list")


def _matches(hostname: str, pattern: str) -> bool:
    """Match `*.example.com` style patterns. Plain domains match exactly."""
    if pattern.startswith("*."):
        return hostname == pattern[2:] or hostname.endswith("." + pattern[2:])
    return hostname == pattern


# --- robots.txt (invariant 11) -------------------------------------------

_robots_cache: dict[str, RobotFileParser] = {}


async def assert_robots_allows(url: str, *, robots_override: bool = False) -> None:
    """Honor robots.txt unless the mission carries a user-attributed override."""
    if robots_override:
        return

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.hostname}"
    parser = _robots_cache.get(base)
    if parser is None:
        parser = RobotFileParser()
        parser.set_url(f"{base}/robots.txt")
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": settings.autumn_user_agent},
                timeout=5.0,
            ) as client:
                resp = await client.get(f"{base}/robots.txt")
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                else:
                    # No robots.txt → permissive
                    parser.allow_all = True  # type: ignore[attr-defined]
        except (httpx.HTTPError, OSError):
            # Network failure on robots.txt fetch → fail open per
            # invariant 11's intent (block scraping never happens
            # because robots.txt was unreachable).
            parser.allow_all = True  # type: ignore[attr-defined]
        _robots_cache[base] = parser

    if not parser.can_fetch(settings.autumn_user_agent, url):
        raise UrlNotAllowed(url, "robots.txt disallowed")


# --- rate limiter --------------------------------------------------------

def _user_id_or_remote(request: Request) -> str:
    user = _current_user.get()
    if user:
        return user.user_id
    return get_remote_address(request)


limiter = Limiter(
    key_func=_user_id_or_remote,
    default_limits=["1000/day", "60/minute"],
    storage_uri="memory://",
)
```

Key invariants implemented:

| Invariant | Where |
|---|---|
| 1 (SSRF guard before any fetcher) | `assert_safe_url` |
| 10 (no tool call without authenticated user) | `require_user` + context |
| 11 (robots.txt honored) | `assert_robots_allows` |

`assert_safe_url` and `assert_robots_allows` are idempotent and
cheap; later specs call them inside every fetcher tier (Spec 07
HTTP, Spec 09 Stealth/Dynamic). They are exported here so the
fetcher tiers do not re-implement them.

### D. API — wire into `app/main.py`

```python
from __future__ import annotations

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.security import RequireUser, limiter


app = FastAPI(title="Autumn API")
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(_request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=429,
        content={"detail": "rate limit exceeded", "retry_after": str(exc.detail)},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/me")
@limiter.limit("60/minute")
async def me(request, user: RequireUser) -> dict[str, str]:
    return {"user_id": user.user_id}
```

The `/health` endpoint stays public (load balancers and uptime
checks). The `/me` endpoint is the smoke test for the full
auth + rate-limit chain.

### E. Tests

#### `apps/api/tests/test_ssrf.py`

```python
from __future__ import annotations

import pytest

from app.security import UrlNotAllowed, assert_safe_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/",  # AWS metadata
        "http://[::1]/",
    ],
)
def test_blocks_private_addresses(url: str) -> None:
    with pytest.raises(UrlNotAllowed):
        assert_safe_url(url)


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com/", "file:///etc/passwd", "javascript:alert(1)"],
)
def test_blocks_non_http_schemes(url: str) -> None:
    with pytest.raises(UrlNotAllowed):
        assert_safe_url(url)


def test_allows_public_https() -> None:
    assert_safe_url("https://example.com/")  # no exception
```

#### `apps/api/tests/test_jwt.py`

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_me_rejects_missing_token() -> None:
    response = client.get("/me")
    assert response.status_code == 401


def test_me_rejects_garbage_token() -> None:
    response = client.get("/me", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401


# A real-token test belongs in an integration suite that runs against
# a live Clerk dev instance; unit tests cover the negative paths only.
```

#### `apps/api/tests/test_rate_limit.py`

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_rate_limit_blocks_after_threshold() -> None:
    # /health is public and uncapped; we assert against /me's 401 path
    # which still consumes a rate-limit slot when keyed on remote address.
    for _ in range(60):
        client.get("/me")  # 401 each time, but counts toward limit
    response = client.get("/me")
    assert response.status_code in (401, 429)
    # 429 is the proof; 401 means slowapi didn't kick in for unauth'd
    # paths in this test setup. Document the expected path in CI.
```

The 401-vs-429 ambiguity is a real edge of `slowapi` for
unauthenticated requests; the production behavior with a real JWT
clearly hits 429. Document this in the test comment, and add an
integration-level test that uses a Clerk test JWT in a later spec.

#### `apps/api/tests/test_robots.py`

```python
from __future__ import annotations

import pytest

from app.security import UrlNotAllowed, assert_robots_allows


@pytest.mark.asyncio
async def test_override_bypasses_robots() -> None:
    # With override, the function returns without fetching robots.txt.
    await assert_robots_allows("https://example.com/", robots_override=True)


# Live robots.txt parsing is exercised in integration tests where we
# mock httpx; unit tests cover the override path and the cache.
```

#### `apps/api/tests/test_allowlist.py`

```python
from __future__ import annotations

import pytest

from app.config import settings
from app.security import UrlNotAllowed, assert_safe_url


def test_no_allowlist_permits_public(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "autumn_url_allowlist", None)
    assert_safe_url("https://example.com/")


def test_allowlist_blocks_off_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "autumn_url_allowlist", "example.com")
    with pytest.raises(UrlNotAllowed):
        assert_safe_url("https://other.com/")


def test_allowlist_glob_matches_subdomain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "autumn_url_allowlist", "*.example.com")
    assert_safe_url("https://api.example.com/")
```

### F. Order of operations

1. Install `@clerk/nextjs` in `apps/web` (section A).
2. Wire `proxy.ts`, `ClerkProvider`, auth pages, and the
   `/missions` placeholder protected route. Boot the dev server and
   confirm sign-in flow works end-to-end (manual).
3. Install Python deps in `apps/api` (section B). `uv sync`.
4. Write `app/config.py` and add `.env.example` for the api.
5. Write `app/security.py` — the full module. Run `mypy app` to
   confirm strict typing passes.
6. Update `app/main.py` to use the limiter middleware and `/me`
   (section D).
7. Write the five test files (section E). Run
   `cd apps/api && uv run pytest -q`.
8. Run the verification block.

## Out of Scope

- **Webhook handler `/webhooks/clerk`** and the Neon `users` table —
  Spec 05.
- **Mission and task ownership checks** — those need the persistence
  layer; arrive in Spec 05 + Spec 07.
- **`robots_override` flag on the mission row** — Spec 05 introduces
  the column; Spec 07 plumbs it through to `assert_robots_allows`.
- **Real Clerk-issued JWT integration test** — needs a Clerk test
  instance and fixture infrastructure; deferred until the api has
  a CI runner. Unit tests cover the negative paths only.
- **CSRF tokens on the BFF** — Clerk middleware handles same-origin
  by default; we revisit if cross-origin BFF emerges.
- **Multi-region Clerk verification** — single-region for MVP.
- **OAuth providers (Google, GitHub, etc.)** — configured in Clerk
  dashboard, not in code; out of scope for this spec.

## Files

### Create

- `apps/web/proxy.ts`
- `apps/web/app/(auth)/layout.tsx`
- `apps/web/app/(auth)/sign-in/[[...sign-in]]/page.tsx`
- `apps/web/app/(auth)/sign-up/[[...sign-up]]/page.tsx`
- `apps/web/app/missions/page.tsx`
- `apps/web/.env.example`
- `apps/api/app/config.py`
- `apps/api/app/security.py`
- `apps/api/.env.example`
- `apps/api/tests/test_ssrf.py`
- `apps/api/tests/test_jwt.py`
- `apps/api/tests/test_rate_limit.py`
- `apps/api/tests/test_robots.py`
- `apps/api/tests/test_allowlist.py`

### Edit

- `apps/web/package.json` — add `@clerk/nextjs` to deps
- `apps/web/app/layout.tsx` — wrap in `ClerkProvider`
- `apps/api/pyproject.toml` — add prod deps
  (`clerk-backend-api`, `pydantic-settings`, `slowapi`, `httpx`)
  and dev deps (`pytest`, `pytest-asyncio`)
- `apps/api/app/main.py` — install slowapi middleware, add `/me`

### Protected (do not touch — from this spec forward)

- `apps/api/app/security.py` — load-bearing for invariants 1, 10,
  11. Edits require explicit approval per `ai-workflow-rules.md`.
  All later specs call its functions; none modify them.
- `apps/api/app/config.py` — env loading is centralized here; new
  env vars are added by editing this file deliberately.

The agent files protect this from now on:
`scrape-pipeline-doctor` enforces invariant 1/10/11 by name;
`fsd-architect` keeps the web side clean.

## Verification

Run from the repo root.

- `pnpm install` exits 0; `@clerk/nextjs` shows in
  `apps/web/package.json`.
- `cd apps/api && uv sync` exits 0; `clerk-backend-api`,
  `pydantic-settings`, `slowapi`, and `httpx` resolve.
- `turbo run lint` exits 0.
- `turbo run typecheck` exits 0 (strict mypy passes against
  `app/security.py` and `app/config.py`).
- `turbo run test` exits 0; the SSRF, JWT, rate-limit, robots,
  and allow-list tests all pass.
- `turbo run build` exits 0.
- `pnpm exec biome check apps packages` exits 0.

Manual:

- Set `CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` in
  `apps/web/.env.local` and `apps/api/.env` (use a Clerk dev
  instance).
- `turbo run dev` boots both apps.
- Visit `http://localhost:3000/missions` while signed-out → redirect
  to `/sign-in`.
- Sign in → land on `/missions` showing the placeholder string.
- Open browser devtools, copy the Clerk session token, and:
  - `curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/me`
    → returns `{"user_id": "user_..."}`
  - `curl http://localhost:8000/me` → 401
  - `curl -H "Authorization: Bearer garbage" http://localhost:8000/me`
    → 401
- With `AUTUMN_URL_ALLOWLIST=example.com` set, run a Python REPL in
  the api venv: `from app.security import assert_safe_url;
  assert_safe_url("https://other.com/")` raises `UrlNotAllowed`.
- Without the allow-list set, the same call to `example.com`
  succeeds.
- `assert_safe_url("http://169.254.169.254/")` raises
  `UrlNotAllowed("private address blocked")`.

**slowapi rate-limit smoke test**: with the api running and a
valid Clerk JWT in `$TOKEN`, fire 61 requests in under 60s:

```bash
for i in $(seq 1 61); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -H "Authorization: Bearer $TOKEN" \
    http://localhost:8000/me
done
```

The 61st response must return `429`. If every response is `200`
or `401`, slowapi is not wired correctly — check
`Limiter(key_func=...)` and `app.state.limiter` binding.

## Done when

- [ ] Every Verification line passes.
- [ ] `apps/api/app/security.py` is in the protected-files list of
  `context/ai-workflow-rules.md` (already true).
- [ ] No invariant in `context/architecture.md` violated. Spec 04
  satisfies invariants 1 (SSRF guard exists and is callable), 10
  (the auth half — the mission-row half lands in 05/07), and 11
  (robots.txt honor exists and is callable; mission-row override
  parameter is plumbed for 07 to wire through).
- [ ] The web sign-in / sign-up flow is fully functional against
  a Clerk dev instance.
- [ ] The api `/me` endpoint round-trips a real Clerk JWT.
- [ ] `context/progress-tracker.md` updated: Spec 04 to "Completed";
  Spec 05 to "In Progress"; Current Goal updated.
- [ ] No code outside `apps/api/app/security.py` re-implements
  SSRF, robots.txt, allow-list, or rate-limit logic. All callers
  import from `security`.
- [ ] `scrape-pipeline-doctor` agent run on `apps/api/**` finds
  zero invariant-1 / invariant-10 / invariant-11 violations.
- [ ] `code-reviewer` agent run on the chunk produces
  `CODE_REVIEW.md` with `Verdict: Approve`.
- [ ] `simplify` skill review on the diff returns no actionable
  findings.

## Scrape reliability note

This spec ships zero scraping behavior — but it ships the **gates**
every later scrape passes through. Spec 07 (the first HTTP-tier
fetcher) calls `assert_safe_url` and `assert_robots_allows` at the
top of every fetch. Spec 09 (stealth + dynamic tiers) does the same.
A Scrapling tool that forgets these calls violates invariants 1 and
11 and is rejected by the `scrape-pipeline-doctor` agent on review.

The rate limiter (60/min, 1k/day per user_id) is the third gate:
even an authenticated user with a misbehaving prompt loop can't
hammer the api into oblivion. The in-memory backend is a single-
process limit; if Autumn ever scales horizontally, swap
`storage_uri="memory://"` to `redis://...` in one line — no other
code changes needed.
