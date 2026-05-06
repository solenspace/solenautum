"""Global concurrency primitives.

Spec 09 ships only the **global** ceilings per `architecture.md`:

- HTTP — 60 in-flight fetches across the whole process.
- Browser — 8 concurrent Playwright/Camoufox sessions across the whole
  process. Invariant 2: every browser session opens inside
  `browser_slot()` so the semaphore acquire-and-release pair is bound
  to the session lifecycle and `CancelledError` cannot leak.

The per-mission ceilings (HTTP 20, browser 3) land in Spec 10 with the
TaskGroup runner.

`http_slot` is exported for symmetry but **not yet wired into
`app.tools.http.scrape_http`** — Spec 10 wires it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# Per `context/architecture.md`: HTTP global 60, browser global 8.
# Invariant 2 binds browser sessions to `browser_slot()`.
_GLOBAL_HTTP = asyncio.Semaphore(60)
_GLOBAL_BROWSER = asyncio.Semaphore(8)


@asynccontextmanager
async def http_slot() -> AsyncIterator[None]:
    """Acquire a slot in the global HTTP semaphore (60).

    Spec 10 wires this into the HTTP tier; today it is unused.
    """
    async with _GLOBAL_HTTP:
        yield


@asynccontextmanager
async def browser_slot() -> AsyncIterator[None]:
    """Acquire a slot in the global browser semaphore (8).

    Invariant 2: every `AsyncStealthySession` / `AsyncDynamicSession`
    (or in 0.2.99, every `StealthyFetcher.async_fetch` /
    `PlayWrightFetcher.async_fetch` call) opens inside this slot. The
    `async with` release-in-finally is automatic — `CancelledError`
    propagates through the `__aexit__` and the semaphore is released.
    """
    async with _GLOBAL_BROWSER:
        yield
