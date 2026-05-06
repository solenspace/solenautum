"""Process-local LRU in front of `saved_selectors`.

Sits between Scrapling's `StorageSystemMixin` callbacks and Postgres so
the hot path on `.css(adaptive=True)` reads from RAM. Sized at 1k
entries (~1-2 MB at saturation per the Spec 13 research note), keyed on
`(domain, purpose)` to honor invariant 8 (selectors namespace by domain
and purpose).

Cross-process consistency is *not* a goal here — the MVP is single-
process. If Autumn ever scales horizontally, swap this out for Redis
or rely on Postgres alone; the Spec 14 reaper covers cross-process
drift in the meantime.
"""

from __future__ import annotations

from typing import Any

from cachetools import LRUCache

_cache: LRUCache[tuple[str, str], dict[str, Any]] = LRUCache(maxsize=1000)


def cache_get(domain: str, purpose: str) -> dict[str, Any] | None:
    return _cache.get((domain, purpose))


def cache_put(domain: str, purpose: str, payload: dict[str, Any]) -> None:
    _cache[(domain, purpose)] = payload


def cache_evict(domain: str, purpose: str) -> None:
    _cache.pop((domain, purpose), None)


def cache_clear() -> None:
    """Test-only helper. Production code never needs to wipe the cache;
    eviction is handled by LRU bound, TTL sweep, and failure-count.
    """
    _cache.clear()
