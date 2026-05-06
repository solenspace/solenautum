"""Single chokepoint for raw-HTML snapshot persistence.

Invariant 9: snapshots are write-once per `task_id`. Every tier tool
(HTTP, stealth, dynamic) calls `persist_snapshot` after a successful
fetch + extract; the helper wraps `BlobStore.put` so the gzip + 10 MB
truncation logic lives in exactly one place. The configured backend
(`r2` in prod, `local` in dev) is read off settings via
`get_blob_store()`.

Tests inject `store=LocalFsBlobStore(root=tmp_path)` to avoid touching
the global cached `get_blob_store()` instance.
"""

from __future__ import annotations

from uuid import UUID

from app.persistence.blob import BlobStore, get_blob_store


async def persist_snapshot(
    *,
    user_id: str,
    mission_id: UUID,
    task_id: UUID,
    raw_html: bytes,
    store: BlobStore | None = None,
) -> tuple[str, bool]:
    """Write a gzipped HTML snapshot to the configured blob store.

    Returns `(snapshot_key, snapshot_truncated)`. Truncation kicks in at
    10 MB raw (the `BlobStore` enforces it).
    """
    blob = store if store is not None else get_blob_store()
    return await blob.put(
        user_id=user_id,
        mission_id=mission_id,
        task_id=task_id,
        body=raw_html,
    )
