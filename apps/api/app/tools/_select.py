"""Main-content selection bridge — sits between every tier tool's fetcher
and Crawl4AI's `MarkdownExtractor`. Honors invariant 8 (selectors namespace
by `(domain, purpose)`).

Two responsibilities:

1. Run the page through Scrapling's adaptive selector for the
   `MAIN_CONTENT` purpose, falling back to similarity-based relocation
   when the literal selector misses on a previously-seen domain.
2. Mirror successful saves to Postgres (write-through), bump hit/failure
   counts, emit `selector_recovered` when adaptive relocation rescues a
   stale selector. The DB writes are explicit `await` calls placed
   *after* Scrapling's synchronous `.css()` returns — never scheduled
   from inside Scrapling's `save()` callback (invariant 3).

The function returns the *scoped* HTML for the matched element, or the
full body if no main-content region was found. Crawl4AI then runs on the
scoped slice, which is meaningfully smaller (and cleaner) than the whole
page on most sites.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from app.persistence.repository import SelectorRepository
from app.persistence.selector_cache import cache_put
from app.sse import emitter
from app.tools._purposes import SelectorPurpose
from autumn_sse_protocol import SseEvent

log = structlog.get_logger()


# Comma-list of common main-content patterns. Scrapling's `.css()` returns
# the first match across the whole list on a normal page; the adaptive
# fallback (`auto_match=True`) re-locates by similarity when the saved
# element's tag/attrs/text drift.
_MAIN_CONTENT_SELECTOR = (
    'main, [role="main"], article, div.main, div#main, div.content, div#content'
)

# Adaptive matching score floor — anything below 70% similarity is treated
# as a miss. Higher values reduce false positives at the cost of more
# heuristic fallbacks.
_ADAPTIVE_PERCENTAGE = 70


async def select_main_content(
    *,
    page: Any,
    domain: str,
    mission_id: UUID,
    task_id: UUID,
    repo: SelectorRepository,
) -> str:
    """Return the inner HTML of the page's main-content region.

    Pre-conditions: the caller's fetch must have included
    `custom_config={"auto_match": True, "storage": ProcessLruStorage,
    "storage_args": {"url": <fetched_url>}}` so `page._storage` is a
    live `ProcessLruStorage` instance.
    """
    purpose = SelectorPurpose.MAIN_CONTENT.value

    # Pre-warm the LRU from Postgres so Scrapling's synchronous
    # `retrieve()` callback can hit cache during the second `.css()`
    # below. `find()` is read-through to the LRU so consecutive calls
    # are free.
    existing = await repo.find(domain, purpose)

    # First pass: literal selector with auto-save. On Scrapling 0.2.99
    # the kwarg is `auto_match` (renamed to `adaptive` in 0.3+, see
    # progress-tracker Open Question 11). We pass `auto_match=False`
    # explicitly so this first pass stays literal — a hit here means the
    # site's DOM matches our saved selector, no recovery emission needed.
    hits = page.css(
        _MAIN_CONTENT_SELECTOR,
        identifier=purpose,
        auto_match=False,
        auto_save=True,
    )

    recovered_via_adaptive = False
    if not hits and existing is not None:
        # Saved selector exists but literal pattern missed. Try
        # similarity-based relocation. `auto_match=True` walks the
        # saved element-properties dict against every node on the page
        # and picks the closest match above the threshold.
        hits = page.css(
            _MAIN_CONTENT_SELECTOR,
            identifier=purpose,
            auto_match=True,
            auto_save=True,
            percentage=_ADAPTIVE_PERCENTAGE,
        )
        if hits:
            recovered_via_adaptive = True
        else:
            new_failure_count = await repo.bump_failure_count(domain, purpose)
            log.info(
                "select_main_content.adaptive_miss",
                domain=domain,
                purpose=purpose,
                failure_count=new_failure_count,
            )

    # Mirror Scrapling's most-recent save to Postgres so the next process
    # / next deploy starts warm. `save()` already wrote to the in-process
    # LRU; `upsert()` overwrites the row dict with the real shape
    # (id, hit_count, failure_count, last_used_at).
    storage = getattr(page, "_storage", None)
    last_save_payload = getattr(storage, "_last_save_payload", None)
    if last_save_payload is not None:
        row = await repo.upsert(domain=domain, purpose=purpose, payload=last_save_payload)
        # Clear so a subsequent call on a different page doesn't re-mirror
        # a stale payload. The lru_cache(64) on the storage class can hand
        # back the same instance for repeat URLs.
        storage._last_save_payload = None  # type: ignore[union-attr]
        cache_put(
            domain,
            purpose,
            {
                "id": str(row.id),
                "payload": row.payload,
                "hit_count": row.hit_count,
                "failure_count": row.failure_count,
                "last_used_at": row.last_used_at.isoformat(),
            },
        )

    if recovered_via_adaptive:
        new_hit_count = await repo.bump_hit_count(domain, purpose)
        # Schema requires `hit_count >= 1`; if the row was concurrently
        # evicted between recovery and the bump, `bump_hit_count` returns
        # 0 and we skip emission rather than violate the contract.
        if new_hit_count >= 1:
            await emitter.emit(
                SseEvent.model_validate(
                    {
                        "type": "selector_recovered",
                        "content": {
                            "domain": domain,
                            "purpose": purpose,
                            "hit_count": new_hit_count,
                        },
                        "mission_id": str(mission_id),
                        "task_id": str(task_id),
                        "seq": 0,
                    }
                )
            )

    if hits:
        first = hits[0]
        # Scrapling's `Adaptor` exposes `html_content` on element results;
        # fall back to `str(...)` for any wrapper that doesn't.
        return getattr(first, "html_content", None) or str(first)
    body = getattr(page, "body", None)
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    return str(body) if body is not None else ""
