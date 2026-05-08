"""Scrapling `StorageSystemMixin` adapter backed by Autumn's process LRU.

Scrapling 0.2.99's `Adaptor.__init__` builds `self._storage = storage(**storage_args)`
when `auto_match=True`. We thread our class through `BaseFetcher.custom_config`
at fetch time so every fetch handed off to `select_main_content` arrives with
a live storage instance ready for `.css()` calls.

Two reasons we keep the storage backing strictly synchronous and in-memory:

1. **Invariant 3.** Scrapling's `save()` and `retrieve()` callbacks fire
   synchronously from inside `.css()`. Scheduling an `asyncio` task for a
   DB write from there would be a detached task — the lifespan TaskGroup
   does not adopt `loop.create_task`. The DB write-through happens
   explicitly from `select_main_content` after `.css()` returns.
2. **Hot path.** `retrieve()` is called once per `.css(adaptive=True)`
   call; an in-memory dict lookup is ~100 ns vs. ~5 ms for a Postgres
   round-trip. `select_main_content` pre-warms the LRU from Postgres
   *before* invoking `.css()` so the synchronous lookup is a hit.

Per-instance flags (`_last_save_payload`) let the wrapper mirror the
serialized element to Postgres at the next yield point without a second
parse pass.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from scrapling.core.storage_adaptors import StorageSystemMixin
from scrapling.core.utils import _StorageTools

from app.persistence.selector_cache import cache_get, cache_put


class HashableStorageArgs(dict):  # type: ignore[type-arg]
    """A `dict` subclass that is hashable, for passing through Scrapling's
    `BaseFetcher.custom_config` without breaking its lru_cache.

    Scrapling 0.2.99 wraps every `StaticEngine`/`PlayWrightEngine` etc. in
    `@lru_cache(2, typed=True)`, with `adaptor_arguments` (a tuple of
    `(key, value)` items derived from `custom_config`) as part of the
    cache key. A regular `dict` value (e.g. `storage_args={"url": ...}`)
    inside that tuple makes the tuple unhashable, so the wrapper raises
    `TypeError: unhashable type: 'dict'` and every real fetch fails.

    Subclassing `dict` and implementing `__hash__` yields a value that is
    still `**`-unpackable into the downstream `storage(**storage_args)`
    call inside `Adaptor.__init__`, so the per-URL namespacing for Spec 13's
    adaptive selectors stays intact.
    """

    def __hash__(self) -> int:  # type: ignore[override]
        return hash(tuple(sorted(self.items())))


# `lru_cache` decorator is hard-required by `scrapling.parser:114-118` —
# the parser asserts `hasattr(storage, "__wrapped__")` before instantiation.
# `maxsize=64` (vs. the spec note's `1`) lets per-domain instances coexist
# without thrashing; the per-process budget is tiny (each instance holds
# only two reference flags).
@lru_cache(maxsize=64, typed=True)
class ProcessLruStorage(StorageSystemMixin):
    """Process-local Scrapling storage adapter.

    `_get_base_url()` (provided by `StorageSystemMixin`) extracts the
    registered domain from `self.url` via `tldextract`, which is exactly
    the half of the `(domain, purpose)` invariant-8 key Scrapling owns.
    The `purpose` half lives in the `identifier` argument the call site
    passes through `.css(..., identifier=...)`.
    """

    def __init__(self, url: str | None = None) -> None:
        super().__init__(url)
        # Tracks the most-recent `save()` payload so `select_main_content`
        # can mirror it to Postgres without re-serializing.
        self._last_save_payload: dict[str, Any] | None = None

    def save(self, element: Any, identifier: str) -> None:
        # `element` is an `lxml.html.HtmlElement` at runtime; typed as
        # `Any` here because lxml ships no stubs and `disallow_any_unimported`
        # would otherwise reject the signature.
        domain = self._get_base_url()
        payload = _StorageTools.element_to_dict(element)
        cache_put(domain, identifier, _wrap_payload(payload))
        self._last_save_payload = payload

    def retrieve(self, identifier: str) -> dict[str, Any] | None:
        domain = self._get_base_url()
        cached = cache_get(domain, identifier)
        if cached is None:
            return None
        # Cache shape stores the row dict; Scrapling expects only the
        # element-properties dict here.
        payload = cached.get("payload") if "payload" in cached else cached
        return payload if isinstance(payload, dict) else None


def _wrap_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Cache shape parity with `repository._to_cache_dict`. When Scrapling
    saves through this storage we don't yet have a row id / hit_count /
    failure_count / last_used_at — those land via the wrapper's explicit
    `repo.upsert(...)` immediately after, which overwrites this entry
    with the real row shape.
    """
    return {
        "id": "",
        "payload": payload,
        "hit_count": 0,
        "failure_count": 0,
        "last_used_at": "",
    }
