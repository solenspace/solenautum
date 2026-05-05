from __future__ import annotations

import uuid

import pytest

from app.persistence.blob import MAX_SNAPSHOT_BYTES, LocalFsBlobStore


@pytest.mark.asyncio
async def test_put_get_roundtrip(tmp_path):
    store = LocalFsBlobStore(root=tmp_path)
    body = b"<html>hi</html>"
    key, truncated = await store.put(
        user_id="u",
        mission_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        body=body,
    )
    assert not truncated
    assert key.endswith(".html.gz")
    assert await store.get(key) == body


@pytest.mark.asyncio
async def test_oversize_truncates(tmp_path):
    store = LocalFsBlobStore(root=tmp_path)
    body = b"x" * (MAX_SNAPSHOT_BYTES + 1024)
    key, truncated = await store.put(
        user_id="u",
        mission_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        body=body,
    )
    assert truncated
    # The retrieved body is exactly the cap; the suffix beyond the cap is dropped.
    assert await store.get(key) == body[:MAX_SNAPSHOT_BYTES]


@pytest.mark.asyncio
async def test_signed_url_is_file_uri(tmp_path):
    store = LocalFsBlobStore(root=tmp_path)
    key, _ = await store.put(
        user_id="u",
        mission_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        body=b"x",
    )
    url = await store.signed_url(key)
    assert url.startswith("file://")
    assert url.endswith(key)
