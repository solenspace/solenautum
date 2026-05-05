from __future__ import annotations

import pytest

from app.security import assert_robots_allows


@pytest.mark.asyncio
async def test_override_bypasses_robots() -> None:
    # With override, the function returns without fetching robots.txt.
    await assert_robots_allows("https://example.com/", robots_override=True)
