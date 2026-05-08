"""TTL sweep for `saved_selectors` — Spec 13's third eviction layer.

Adopted by the FastAPI lifespan TaskGroup so cancellation on shutdown is
structured (invariant 3). Catches `Exception` per iteration so one bad
DB read can't take down the loop, but lets `CancelledError` propagate.
"""

from __future__ import annotations

import asyncio

import structlog

from app.persistence.repository import SelectorRepository

log = structlog.get_logger()


_SWEEP_INTERVAL_S = 6 * 3600  # 6 hours
_TTL_DAYS = 30


async def selector_sweep_loop(
    *,
    interval_s: float = _SWEEP_INTERVAL_S,
    ttl_days: int = _TTL_DAYS,
) -> None:
    """Run forever; evict saved selectors older than `ttl_days`.

    Parameters are injectable so the unit test can drive the loop with a
    short interval without sleeping for hours.
    """
    repo = SelectorRepository()
    while True:
        try:
            await asyncio.sleep(interval_s)
            count = await repo.evict_older_than(days=ttl_days)
            if count > 0:
                log.info("selector_sweep.evicted", count=count)
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("selector_sweep.failed")
