"""Orphan-mission reaper — Spec 14's safety net for stuck missions.

Adopted by the FastAPI lifespan TaskGroup so cancellation on shutdown is
structured (invariant 3). Catches `Exception` per iteration so one bad
DB read can't take down the loop, but lets `CancelledError` propagate.

Reaps two cases:
- Missions in `pending` status older than `_TIMEOUT` (the runner died
  before it could flip the row to `running`).
- Missions in `running` status with `phase = 'awaiting_approval'` older
  than `_TIMEOUT` (the user opened a description-mode mission, parked
  on the approval gate, and never returned).

Missions in plain `running` (no `awaiting_approval`) are NOT reaped here
— detecting "stuck running" requires per-task heartbeats and is out of
scope for Spec 14.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.persistence.repository import MissionRepository

log = logging.getLogger(__name__)


_SWEEP_INTERVAL_S = 5 * 60  # 5 minutes
_TIMEOUT = timedelta(hours=1)


async def orphan_reaper_loop(
    *,
    interval_s: float = _SWEEP_INTERVAL_S,
    orphan_age: timedelta = _TIMEOUT,
) -> None:
    """Run forever; cancel orphaned missions older than `orphan_age`.

    Parameters are injectable so the unit test can drive the loop with a
    short interval / orphan-age without sleeping for hours. The keyword
    is named `orphan_age` (not `timeout`) so ruff's ASYNC109 rule does
    not mistake it for an asyncio cancellation deadline parameter.
    """
    repo = MissionRepository()
    while True:
        try:
            await asyncio.sleep(interval_s)
            cutoff = datetime.now(UTC) - orphan_age
            count = await repo.reap_orphans(cutoff=cutoff)
            if count > 0:
                log.info("orphan_reaper.reaped", extra={"count": count})
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("orphan_reaper.failed")
