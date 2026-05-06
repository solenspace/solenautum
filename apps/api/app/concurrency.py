"""Global and per-mission concurrency primitives.

Two layers, both required by `architecture.md`:

- **Global (process-wide)** — HTTP 60, browser 8. Ship in Spec 09 and stay
  here as `_GLOBAL_HTTP` / `_GLOBAL_BROWSER`. Bound by `http_slot()` and
  `browser_slot()` for callers that operate outside a mission scope.
- **Per-mission** — HTTP 20, browser 3. Spec 10 adds `MissionSemaphores`,
  bound to the running task via a `ContextVar` so tier tools can acquire
  a layered slot without changing every signature in the call chain.

Acquisition order is **per-mission first, then global**, stacked under one
`async with`. Release order is the reverse via the stacked exits.
Invariant 2 (browser session inside `browser_slot()`) holds because the
inner `async with` enters the global slot before the browser session
opens.

`asyncio.TaskGroup.create_task` propagates the context, so a per-mission
task spawned inside `with_mission_semaphores(sems)` inherits the
binding without explicit threading.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass

# Per `context/architecture.md`: HTTP global 60, browser global 8.
# Invariant 2 binds browser sessions to `browser_slot()`.
_GLOBAL_HTTP = asyncio.Semaphore(60)
_GLOBAL_BROWSER = asyncio.Semaphore(8)


@asynccontextmanager
async def http_slot() -> AsyncIterator[None]:
    """Acquire a slot in the global HTTP semaphore (60).

    Direct use is reserved for callers without a mission scope; mission
    code goes through `MissionSemaphores.http_slot()` (which acquires
    this slot inside the per-mission slot).
    """
    async with _GLOBAL_HTTP:
        yield


@asynccontextmanager
async def browser_slot() -> AsyncIterator[None]:
    """Acquire a slot in the global browser semaphore (8).

    Invariant 2: every browser session opens inside this slot. The
    `async with` release-in-finally is automatic — `CancelledError`
    propagates through the `__aexit__` and the semaphore is released.

    Direct use is reserved for callers without a mission scope; mission
    code goes through `MissionSemaphores.browser_slot()` so the
    per-mission ceiling (3) layers over the global (8).
    """
    async with _GLOBAL_BROWSER:
        yield


@dataclass(slots=True)
class MissionSemaphores:
    """Per-mission tier ceilings. Layered with the globals.

    HTTP-20 / browser-3 prevent a single 20-URL mission from saturating
    the process-wide budgets. Two missions running in parallel each get
    their own per-mission ceiling but compete for the same global slots.
    """

    http: asyncio.Semaphore
    browser: asyncio.Semaphore

    @classmethod
    def fresh(cls) -> MissionSemaphores:
        return cls(
            http=asyncio.Semaphore(20),
            browser=asyncio.Semaphore(3),
        )

    @asynccontextmanager
    async def http_slot(self) -> AsyncIterator[None]:
        """Acquire per-mission HTTP slot, then global. Release reverse."""
        async with self.http, _GLOBAL_HTTP:
            yield

    @asynccontextmanager
    async def browser_slot(self) -> AsyncIterator[None]:
        """Acquire per-mission browser slot, then global. Release reverse.

        Invariant 2 holds: the browser session opens inside the global
        slot, and `CancelledError` unwinds both `async with` exits.
        """
        async with self.browser, _GLOBAL_BROWSER:
            yield


# Tier tools resolve the active mission's semaphores via this context-var.
# `asyncio.TaskGroup.create_task` propagates the context, so a per-task
# coroutine inherits the binding from its mission runner.
_active_semaphores: ContextVar[MissionSemaphores | None] = ContextVar(
    "active_semaphores",
    default=None,
)


@asynccontextmanager
async def with_mission_semaphores(
    sems: MissionSemaphores,
) -> AsyncIterator[None]:
    """Bind per-mission semaphores to the current task's context.

    Tools resolve via `current_mission_semaphores()` and acquire layered
    slots without per-call argument threading.
    """
    token = _active_semaphores.set(sems)
    try:
        yield
    finally:
        _active_semaphores.reset(token)


def current_mission_semaphores() -> MissionSemaphores:
    """Return the semaphores bound to the current task.

    Defensive fallback: if a tier tool is invoked outside a mission run
    (e.g. a unit test that bypasses the runner), return a fresh instance
    so the global slot still applies but the per-mission ceiling is
    isolated to this call. This must not be relied on in production —
    every mission task runs inside `with_mission_semaphores(...)`.
    """
    sems = _active_semaphores.get()
    if sems is None:
        return MissionSemaphores.fresh()
    return sems
