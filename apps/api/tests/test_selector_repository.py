"""Spec 13 — `SelectorRepository` integration tests.

Coverage targets:
  * `find()` round-trip + LRU read-through behavior
  * `upsert()` ON CONFLICT atomic semantics (closes Open Question 6)
  * `bump_hit_count` returns monotonic non-decreasing values
  * Three consecutive `bump_failure_count` calls evict the row
  * `evict_older_than` removes stale rows + clears their cache entries
  * `delete()` evicts both the row and its cache entry
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import update

from app.config import settings
from app.persistence.db import transaction
from app.persistence.models import SavedSelector
from app.persistence.repository import SelectorRepository
from app.persistence.selector_cache import cache_clear, cache_get

pytestmark = pytest.mark.skipif(
    settings.database_url is None,
    reason="DATABASE_URL is not set; persistence-layer tests need a real Postgres",
)


@pytest_asyncio.fixture(autouse=True)
async def _isolate_state():
    """Each test starts with a clean LRU + a clean `saved_selectors` table.
    `saved_selectors` has no RLS so tests share a deployment-scoped row
    space — DELETE before each test keeps cases independent.
    """
    cache_clear()
    async with transaction() as session:
        await session.execute(SavedSelector.__table__.delete())
    yield
    cache_clear()
    async with transaction() as session:
        await session.execute(SavedSelector.__table__.delete())


@pytest.mark.asyncio
async def test_upsert_then_find_round_trip():
    repo = SelectorRepository()
    saved = await repo.upsert(domain="example.com", purpose="main_content", payload={"tag": "main"})

    found = await repo.find("example.com", "main_content")
    assert found is not None
    assert found.id == saved.id
    assert found.payload == {"tag": "main"}
    assert found.hit_count == 0
    assert found.failure_count == 0


@pytest.mark.asyncio
async def test_find_populates_lru_on_db_hit():
    repo = SelectorRepository()
    await repo.upsert(domain="ex.com", purpose="main_content", payload={"tag": "article"})
    cache_clear()

    assert cache_get("ex.com", "main_content") is None
    found = await repo.find("ex.com", "main_content")
    assert found is not None
    assert cache_get("ex.com", "main_content") is not None


@pytest.mark.asyncio
async def test_concurrent_upserts_do_not_collide():
    """ON CONFLICT DO UPDATE closes the SELECT-then-INSERT race.

    Without it, both coroutines miss the SELECT, both attempt INSERT, and
    one raises `UniqueViolationError` on the (domain, purpose) index.
    """
    repo = SelectorRepository()
    domain, purpose = "racy.example", "main_content"

    results = await asyncio.gather(
        repo.upsert(domain=domain, purpose=purpose, payload={"tag": "main", "n": 1}),
        repo.upsert(domain=domain, purpose=purpose, payload={"tag": "main", "n": 2}),
        repo.upsert(domain=domain, purpose=purpose, payload={"tag": "main", "n": 3}),
    )
    assert all(r is not None for r in results)
    found = await repo.find(domain, purpose)
    assert found is not None
    # One of the three payloads won; identity is irrelevant — what matters
    # is that we ended up with exactly one row.
    assert found.payload["tag"] == "main"


@pytest.mark.asyncio
async def test_upsert_resets_failure_count():
    repo = SelectorRepository()
    await repo.upsert(domain="dom.example", purpose="main_content", payload={"tag": "old"})
    await repo.bump_failure_count("dom.example", "main_content")
    await repo.bump_failure_count("dom.example", "main_content")

    refreshed = await repo.upsert(
        domain="dom.example", purpose="main_content", payload={"tag": "new"}
    )
    assert refreshed.payload == {"tag": "new"}
    assert refreshed.failure_count == 0


@pytest.mark.asyncio
async def test_upsert_preserves_hit_count_on_conflict():
    """Spec 13 invariant: only `bump_hit_count` mutates `hit_count`.

    A subsequent `upsert` (e.g. when Scrapling re-saves a refreshed
    payload) must leave the recovery counter untouched — otherwise
    a successful save would silently wipe the operator's view of how
    often adaptive matching has rescued this domain.
    """
    repo = SelectorRepository()
    await repo.upsert(domain="hits.example", purpose="main_content", payload={"tag": "v1"})
    await repo.bump_hit_count("hits.example", "main_content")
    await repo.bump_hit_count("hits.example", "main_content")

    refreshed = await repo.upsert(
        domain="hits.example", purpose="main_content", payload={"tag": "v2"}
    )
    assert refreshed.payload == {"tag": "v2"}
    assert refreshed.hit_count == 2


@pytest.mark.asyncio
async def test_bump_hit_count_is_monotonic():
    repo = SelectorRepository()
    await repo.upsert(domain="hits.example", purpose="main_content", payload={"tag": "main"})

    a = await repo.bump_hit_count("hits.example", "main_content")
    b = await repo.bump_hit_count("hits.example", "main_content")
    c = await repo.bump_hit_count("hits.example", "main_content")
    assert a == 1
    assert b == 2
    assert c == 3


@pytest.mark.asyncio
async def test_third_failure_evicts_row_and_cache():
    repo = SelectorRepository()
    await repo.upsert(domain="fail.example", purpose="main_content", payload={"tag": "main"})

    assert await repo.bump_failure_count("fail.example", "main_content") == 1
    assert await repo.bump_failure_count("fail.example", "main_content") == 2
    third = await repo.bump_failure_count("fail.example", "main_content")
    assert third >= 3

    assert await repo.find("fail.example", "main_content") is None
    assert cache_get("fail.example", "main_content") is None


@pytest.mark.asyncio
async def test_delete_evicts_cache():
    repo = SelectorRepository()
    await repo.upsert(domain="del.example", purpose="main_content", payload={"tag": "main"})
    assert cache_get("del.example", "main_content") is not None

    await repo.delete("del.example", "main_content")
    assert cache_get("del.example", "main_content") is None
    assert await repo.find("del.example", "main_content") is None


@pytest.mark.asyncio
async def test_evict_older_than_removes_stale_rows():
    repo = SelectorRepository()
    await repo.upsert(domain="old.example", purpose="main_content", payload={"tag": "main"})
    await repo.upsert(domain="fresh.example", purpose="main_content", payload={"tag": "main"})

    # Push the "old" row's last_used_at 31 days into the past via direct
    # SQL — the public API doesn't expose backdating.
    cutoff = datetime.now(UTC) - timedelta(days=31)
    async with transaction() as session:
        await session.execute(
            update(SavedSelector)
            .where(SavedSelector.domain == "old.example")
            .values(last_used_at=cutoff)
        )

    count = await repo.evict_older_than(days=30)
    assert count == 1
    assert await repo.find("old.example", "main_content") is None
    assert await repo.find("fresh.example", "main_content") is not None
    assert cache_get("old.example", "main_content") is None
