from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from autumn_sse_protocol import SseEvent

log = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_S = 15
_BUFFER_CAPACITY = 200
_TERMINATE_GRACE_S = 60
_QUEUE_MAX = 512


@dataclass(slots=True)
class _MissionState:
    """Per-mission emitter state. One queue and one ring buffer enforce the
    single-serialization rule (invariant 4); `terminated_at` drives the 60s
    eviction grace after a mission-level done/error.
    """

    seq: int = 0
    queue: asyncio.Queue[tuple[int, dict[str, Any]] | None] = field(
        default_factory=lambda: asyncio.Queue(maxsize=_QUEUE_MAX),
    )
    buffer: deque[tuple[int, dict[str, Any]]] = field(
        default_factory=lambda: deque(maxlen=_BUFFER_CAPACITY),
    )
    terminated_at: float | None = None


class _RunnableMission(Protocol):
    """Structural type for `MissionRunner` consumed by `adopt_runner`.

    Avoids the runner→sse→runner import cycle: the emitter only needs an
    awaitable `run()`. The Spec 14 cancel endpoints reach in via
    `SseEmitter.get_active_runner(mission_id)` and call
    `request_cancellation()` / `cancel_task(task_id)` on the live runner.
    """

    def run(self) -> Awaitable[None]: ...


class SseEmitter:
    """Process-wide SSE emitter. Implements the Spec 06 contract: single
    per-mission queue, monotonic `seq`, 200-event ring buffer, `Last-Event-ID`
    resume, terminal-event eviction with 60s grace.

    Also owns runner adoption (Spec 10): the FastAPI `lifespan` binds an
    `asyncio.TaskGroup` here, and `adopt_runner` hands each new
    `MissionRunner` to that group so the runner runs to completion in a
    structured-concurrency-safe parent (invariant 3) while the
    `POST /missions` handler returns the `mission_id` immediately.
    """

    def __init__(self) -> None:
        self._missions: dict[UUID, _MissionState] = {}
        self._lock = asyncio.Lock()
        self._lifespan_tg: asyncio.TaskGroup | None = None
        # Spec 14: process-level registry of running mission runners so the
        # cancel endpoints can route a request to the live `MissionRunner`
        # without going through the DB. Populated by `adopt_runner`,
        # cleaned up by `_shielded_run`'s `finally`.
        self._active_runners: dict[UUID, _RunnableMission] = {}

    async def emit(self, event: SseEvent) -> None:  # type: ignore[no-any-unimported]
        """Validate the event, assign a monotonic `seq`, append to the ring
        buffer, and push onto the per-mission queue. Two producers cannot
        interleave because the lock orders the seq + buffer + enqueue triplet.
        """
        payload = event.model_dump(mode="json")
        mission_id = UUID(payload["mission_id"])

        async with self._lock:
            state = self._missions.setdefault(mission_id, _MissionState())
            seq = state.seq
            payload["seq"] = seq
            state.seq += 1
            state.buffer.append((seq, payload))
            if event.root.type in {"done", "error"} and event.root.task_id is None:
                state.terminated_at = time.monotonic()
            try:
                state.queue.put_nowait((seq, payload))
            except asyncio.QueueFull:
                log.warning(
                    "sse.queue_full",
                    extra={
                        "mission_id": str(mission_id),
                        "seq": seq,
                        "type": payload.get("type"),
                    },
                )

    @asynccontextmanager
    async def stream(
        self, mission_id: UUID, *, last_event_id: int | None
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        """Yield an async iterator of SSE-framed bytes for one client. The
        replay slice and the queue drain run together under the lock so a
        concurrent `emit()` can't slip an event between the two — every event
        is delivered exactly once.

        If the mission state has already been evicted (60s after a terminal
        event), `replay` is `None` and the iterator emits one synthetic
        `resume_lost` and closes — never silently allocates a fresh empty
        state, which would hang the client on a queue with no producer.
        """
        async with self._lock:
            state = self._missions.get(mission_id)
            if state is None:
                replay: list[tuple[int, dict[str, Any]]] | None = None
            else:
                replay = self._replay_slice(state, last_event_id)
                # Drain queue events that are already covered by the buffer/
                # replay so the live-forward loop only sees events emitted
                # *after* this stream opened.
                while True:
                    try:
                        state.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

        async def _iterator() -> AsyncIterator[bytes]:
            if replay is None or state is None:
                yield self._format_resume_lost(mission_id)
                return

            for _, payload in replay:
                yield self._format(payload)
                if self._is_mission_terminal(payload):
                    return

            while True:
                try:
                    item = await asyncio.wait_for(state.queue.get(), timeout=_HEARTBEAT_INTERVAL_S)
                except TimeoutError:
                    yield b": heartbeat\n\n"
                    continue

                if item is None:
                    break  # explicit close sentinel

                _, payload = item
                yield self._format(payload)

                if self._is_mission_terminal(payload):
                    break

        try:
            yield _iterator()
        finally:
            await self._maybe_evict(mission_id)

    @staticmethod
    def _is_mission_terminal(payload: dict[str, Any]) -> bool:
        return payload.get("type") in {"done", "error"} and payload.get("task_id") is None

    @staticmethod
    def _replay_slice(
        state: _MissionState, last_event_id: int | None
    ) -> list[tuple[int, dict[str, Any]]] | None:
        """Return events with `seq > last_event_id`, or `None` if the buffer
        no longer covers the requested resume point.
        """
        if last_event_id is None:
            return list(state.buffer)
        if not state.buffer:
            return []
        oldest_seq = state.buffer[0][0]
        if oldest_seq > last_event_id + 1:
            return None  # caller's last_event_id predates the buffer
        return [(s, p) for s, p in state.buffer if s > last_event_id]

    @staticmethod
    def _format(payload: dict[str, Any]) -> bytes:
        return (
            f"id: {payload['seq']}\n"
            f"event: {payload['type']}\n"
            f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
        ).encode()

    @staticmethod
    def _format_resume_lost(mission_id: UUID) -> bytes:
        """Synthetic out-of-band error emitted when the ring buffer no longer
        covers the requested resume point (or the mission state has been
        evicted past the 60s grace). Not added to the buffer — one-shot.

        We deliberately omit the `id:` line so a well-behaved EventSource
        client does NOT update its `Last-Event-ID` to this synthetic seq,
        which would loop the client through the same error on every
        reconnect attempt.
        """
        payload = {
            "type": "error",
            "content": {"code": "resume_lost", "message": "buffer evicted"},
            "mission_id": str(mission_id),
            "seq": 0,
        }
        return (
            f"event: {payload['type']}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
        ).encode()

    async def _maybe_evict(self, mission_id: UUID) -> None:
        async with self._lock:
            state = self._missions.get(mission_id)
            if state is None or state.terminated_at is None:
                return
            if time.monotonic() - state.terminated_at > _TERMINATE_GRACE_S:
                self._missions.pop(mission_id, None)

    def bind_lifespan_tg(self, tg: asyncio.TaskGroup) -> None:
        """Bind the FastAPI lifespan-scoped TaskGroup. Called from
        `app.main.lifespan` before the `yield`.

        Idempotent re-binds are not supported — the lifespan creates one
        group per process. A second call indicates a boot bug.
        """
        if self._lifespan_tg is not None:
            raise RuntimeError(
                "lifespan TaskGroup already bound; SseEmitter.bind_lifespan_tg "
                "is intended to be called exactly once per process"
            )
        self._lifespan_tg = tg

    async def adopt_runner(self, mission_id: UUID, runner: _RunnableMission) -> None:
        """Hand a `MissionRunner` to the lifespan TaskGroup.

        Wraps `runner.run()` in a logging shield so an unhandled mission
        error does not propagate up the lifespan group (which would
        cancel every other in-flight mission). The runner itself is
        responsible for emitting per-task and mission-level terminal
        events; if it fails partway through, that's the bug we want to
        surface in logs and Langfuse, not an SSE blackout.

        The runner is registered in `_active_runners` *before* the task
        is scheduled so a `DELETE /missions/{id}` that arrives between
        adoption and the runner's first `await` still finds the live
        runner via `get_active_runner`.
        """
        if self._lifespan_tg is None:
            raise RuntimeError(
                "lifespan TaskGroup not bound; call bind_lifespan_tg from "
                "the FastAPI lifespan before serving traffic"
            )
        self._register_runner(mission_id, runner)
        self._lifespan_tg.create_task(
            _shielded_run(mission_id, runner),
            name=f"mission:{mission_id}",
        )

    def get_active_runner(self, mission_id: UUID) -> _RunnableMission | None:
        """Return the live `_RunnableMission` for `mission_id` if the
        runner is still in this process, else `None`. The Spec 14 cancel
        endpoints use this to route `request_cancellation()` /
        `cancel_task(task_id)` to the running coroutine.
        """
        return self._active_runners.get(mission_id)

    def _register_runner(self, mission_id: UUID, runner: _RunnableMission) -> None:
        """Add the runner to the active registry. Internal — only
        `adopt_runner` calls this. A description-mode wrapper may
        re-register itself here when its inner `MissionRunner` is
        constructed mid-flight (so per-task cancels route through to
        the inner coroutine).
        """
        self._active_runners[mission_id] = runner

    def _release_runner(self, mission_id: UUID) -> None:
        """Remove the runner from the active registry. Internal —
        `_shielded_run`'s `finally` calls this once the runner returns,
        whether normally or via an unhandled exception.
        """
        self._active_runners.pop(mission_id, None)


async def _shielded_run(mission_id: UUID, runner: _RunnableMission) -> None:
    """Run a MissionRunner; log unhandled errors instead of letting them
    abort the lifespan TaskGroup. The `finally` clause releases the
    runner from the registry so subsequent cancel requests fall through
    to the rare-edge synthetic-terminal branch.
    """
    try:
        await runner.run()
    except Exception:
        log.exception(
            "mission.runner_unhandled_error",
            extra={"mission_id": str(mission_id)},
        )
    finally:
        emitter._release_runner(mission_id)


emitter = SseEmitter()
