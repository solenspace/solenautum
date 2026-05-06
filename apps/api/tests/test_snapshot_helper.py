from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.persistence.blob import LocalFsBlobStore
from app.persistence.snapshot import persist_snapshot


@pytest.mark.asyncio
async def test_persist_snapshot_round_trip(tmp_path: Path) -> None:
    store = LocalFsBlobStore(root=tmp_path)
    body = b"<html><body>hello world</body></html>"

    key, truncated = await persist_snapshot(
        user_id="user_1",
        mission_id=uuid4(),
        task_id=uuid4(),
        raw_html=body,
        store=store,
    )

    assert truncated is False
    assert key  # non-empty
    assert await store.get(key) == body
