"""Spec 13 — `select_main_content` behavioral tests.

Coverage targets:
  * First run with literal-selector hit → row written, no
    `selector_recovered` event.
  * Second run with drifted DOM where literal misses but adaptive
    relocates → `selector_recovered` event with `hit_count >= 1`.
  * Three consecutive adaptive misses → row deleted from DB + LRU.

Scrapling's actual element-relocation logic isn't under test here —
that's the library's job. We exercise the *wrapper*: pre-warm, branching
on literal vs. adaptive, DB write-through, event emission, failure-count
escalation. Scrapling's `Adaptor.css()` is replaced with a fake whose
behavior is dictated per-test.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio

from app.config import settings
from app.persistence.db import transaction
from app.persistence.models import SavedSelector
from app.persistence.repository import SelectorRepository
from app.persistence.selector_cache import cache_clear
from app.sse import emitter
from app.tools._select import select_main_content

pytestmark = pytest.mark.skipif(
    settings.database_url is None,
    reason="DATABASE_URL is not set; persistence-layer tests need a real Postgres",
)


@pytest_asyncio.fixture(autouse=True)
async def _isolate_state():
    cache_clear()
    async with transaction() as session:
        await session.execute(SavedSelector.__table__.delete())
    yield
    cache_clear()
    async with transaction() as session:
        await session.execute(SavedSelector.__table__.delete())
    # Drain emitter ring buffers so cross-test events don't bleed.
    emitter._missions.clear()


class _FakeStorage:
    """Stand-in for `ProcessLruStorage`. Tracks a single saved payload."""

    def __init__(self, *, save_payload: dict[str, Any] | None = None) -> None:
        self._last_save_payload = save_payload


class _FakeElement:
    def __init__(self, html: str) -> None:
        self.html_content = html


class _FakePage:
    """Minimal Scrapling Response stand-in driven by a `css_responses` queue.

    Each call to `.css()` pops the next response. The wrapper makes at
    most two calls per `select_main_content` invocation (literal then
    adaptive), so two-element queues are sufficient.
    """

    def __init__(
        self,
        *,
        url: str,
        body: str,
        css_responses: list[list[_FakeElement]],
        storage: _FakeStorage | None = None,
    ) -> None:
        self.url = url
        self.body = body
        self._storage = storage
        self._css_queue = css_responses

    def css(
        self,
        selector: str,
        *,
        identifier: str = "",
        auto_match: bool = False,
        auto_save: bool = False,
        percentage: int = 0,
    ) -> list[_FakeElement]:
        del selector, identifier, auto_match, auto_save, percentage
        if not self._css_queue:
            return []
        return self._css_queue.pop(0)


def _ids() -> tuple[Any, Any]:
    return uuid4(), uuid4()


@pytest.mark.asyncio
async def test_first_run_saves_selector_no_event_emitted():
    repo = SelectorRepository()
    storage = _FakeStorage(save_payload={"tag": "main", "attributes": {}})
    page = _FakePage(
        url="https://first.example/",
        body="<html><body><main>OK</main></body></html>",
        css_responses=[[_FakeElement("<main>OK</main>")]],
        storage=storage,
    )
    mission_id, task_id = _ids()

    main_html = await select_main_content(
        page=page,
        domain="first.example",
        mission_id=mission_id,
        task_id=task_id,
        repo=repo,
    )

    assert main_html == "<main>OK</main>"

    found = await repo.find("first.example", "main_content")
    assert found is not None
    assert found.payload == {"tag": "main", "attributes": {}}
    assert found.hit_count == 0  # no recovery happened

    # No `selector_recovered` event landed in the emitter for this mission.
    state = emitter._missions.get(mission_id)
    if state is not None:
        types = {ev[1]["type"] for ev in state.buffer}
        assert "selector_recovered" not in types


@pytest.mark.asyncio
async def test_drifted_dom_recovers_via_adaptive_emits_event():
    repo = SelectorRepository()
    # Seed an existing saved selector so the wrapper takes the
    # adaptive-fallback branch on a literal miss.
    await repo.upsert(
        domain="drifted.example",
        purpose="main_content",
        payload={"tag": "main", "attributes": {}},
    )

    storage = _FakeStorage(save_payload=None)
    page = _FakePage(
        url="https://drifted.example/",
        body="<html><body><article>NEW</article></body></html>",
        # First call (literal) returns empty; second (adaptive) finds <article>.
        css_responses=[[], [_FakeElement("<article>NEW</article>")]],
        storage=storage,
    )
    mission_id, task_id = _ids()

    main_html = await select_main_content(
        page=page,
        domain="drifted.example",
        mission_id=mission_id,
        task_id=task_id,
        repo=repo,
    )

    assert main_html == "<article>NEW</article>"

    # Hit-count bumped + event emitted.
    found = await repo.find("drifted.example", "main_content")
    assert found is not None
    assert found.hit_count == 1

    state = emitter._missions.get(mission_id)
    assert state is not None
    types = [ev[1]["type"] for ev in state.buffer]
    assert "selector_recovered" in types
    selector_event = next(ev[1] for ev in state.buffer if ev[1]["type"] == "selector_recovered")
    assert selector_event["content"]["domain"] == "drifted.example"
    assert selector_event["content"]["purpose"] == "main_content"
    assert selector_event["content"]["hit_count"] >= 1


@pytest.mark.asyncio
async def test_three_adaptive_misses_evict_row():
    repo = SelectorRepository()
    await repo.upsert(
        domain="brittle.example",
        purpose="main_content",
        payload={"tag": "main", "attributes": {}},
    )

    for _ in range(3):
        page = _FakePage(
            url="https://brittle.example/",
            body="<html><body>nothing matches</body></html>",
            css_responses=[[], []],  # literal miss, adaptive miss
            storage=_FakeStorage(save_payload=None),
        )
        mission_id, task_id = _ids()
        await select_main_content(
            page=page,
            domain="brittle.example",
            mission_id=mission_id,
            task_id=task_id,
            repo=repo,
        )

    # After three consecutive adaptive failures the row is gone.
    assert await repo.find("brittle.example", "main_content") is None


@pytest.mark.asyncio
async def test_returns_full_body_when_no_main_match_and_no_existing_selector():
    repo = SelectorRepository()
    storage = _FakeStorage(save_payload=None)
    page = _FakePage(
        url="https://barebones.example/",
        body="<html><body>plain</body></html>",
        css_responses=[[]],  # literal miss; no `existing` so no adaptive call
        storage=storage,
    )
    mission_id, task_id = _ids()

    main_html = await select_main_content(
        page=page,
        domain="barebones.example",
        mission_id=mission_id,
        task_id=task_id,
        repo=repo,
    )
    assert main_html == "<html><body>plain</body></html>"
    # No selector ever saved → no row, no event, no failure bump.
    assert await repo.find("barebones.example", "main_content") is None
