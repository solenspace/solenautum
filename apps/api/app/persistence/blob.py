from __future__ import annotations

import gzip
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import Final
from uuid import UUID

import boto3
from botocore.config import Config

from app.config import settings

MAX_SNAPSHOT_BYTES: Final = 10 * 1024 * 1024  # 10 MB raw HTML cap


class BlobStore(ABC):
    @abstractmethod
    async def put(
        self, *, user_id: str, mission_id: UUID, task_id: UUID, body: bytes
    ) -> tuple[str, bool]:
        """Store the body. Returns `(key, truncated)`. Body is truncated to
        MAX_SNAPSHOT_BYTES (raw) before gzipping.
        """

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Return the gunzipped body."""

    @abstractmethod
    async def signed_url(self, key: str, *, expires_in_seconds: int = 3600) -> str:
        """Return a time-limited URL to fetch the object."""


def _key(user_id: str, mission_id: UUID, task_id: UUID) -> str:
    return f"{user_id}/{mission_id}/{task_id}.html.gz"


def _gzip_truncate(body: bytes) -> tuple[bytes, bool]:
    truncated = len(body) > MAX_SNAPSHOT_BYTES
    if truncated:
        body = body[:MAX_SNAPSHOT_BYTES]
    return gzip.compress(body), truncated


class R2BlobStore(BlobStore):
    def __init__(self) -> None:
        if (
            settings.r2_account_id is None
            or settings.r2_access_key_id is None
            or settings.r2_secret_access_key is None
            or settings.r2_bucket is None
        ):
            raise RuntimeError("BLOB_STORE_BACKEND=r2 but one or more R2_* env vars are missing")
        self._bucket = settings.r2_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )

    async def put(
        self, *, user_id: str, mission_id: UUID, task_id: UUID, body: bytes
    ) -> tuple[str, bool]:
        # boto3 is sync; for MVP we accept the blocking call. Spec 15
        # (hardening) revisits with aioboto3 if profiling demands it.
        key = _key(user_id, mission_id, task_id)
        gz, truncated = _gzip_truncate(body)
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=gz,
            ContentType="text/html",
            ContentEncoding="gzip",
        )
        return key, truncated

    async def get(self, key: str) -> bytes:
        obj = self._client.get_object(Bucket=self._bucket, Key=key)
        return gzip.decompress(obj["Body"].read())

    async def signed_url(self, key: str, *, expires_in_seconds: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in_seconds,
        )


class LocalFsBlobStore(BlobStore):
    """Dev / test backend. Writes under `apps/api/data/snapshots/` by default.
    Uses sync `pathlib` writes inside async methods — same MVP debt shape as
    `R2BlobStore`; revisit alongside aioboto3 in Spec 15 if profiling needs it.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path("data/snapshots")
        self._root.mkdir(parents=True, exist_ok=True)

    async def put(
        self, *, user_id: str, mission_id: UUID, task_id: UUID, body: bytes
    ) -> tuple[str, bool]:
        key = _key(user_id, mission_id, task_id)
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        gz, truncated = _gzip_truncate(body)
        path.write_bytes(gz)
        return key, truncated

    async def get(self, key: str) -> bytes:
        return gzip.decompress((self._root / key).read_bytes())

    async def signed_url(self, key: str, *, expires_in_seconds: int = 3600) -> str:  # noqa: ARG002
        # Dev-only: a `file://` URL is not actually signed; never used in prod.
        return f"file://{(self._root / key).resolve()}"


@lru_cache(maxsize=1)
def get_blob_store() -> BlobStore:
    if settings.blob_store_backend == "r2":
        return R2BlobStore()
    return LocalFsBlobStore()
