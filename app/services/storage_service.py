"""Pluggable photo storage.

Backends:
  - LocalStorage   — writes to disk under LOCAL_UPLOAD_DIR (dev default)
  - S3Storage      — uploads to S3 via boto3 in a worker thread

Tests override `get_storage` with an in-memory fake.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Protocol

from fastapi import HTTPException, status

from app.core.config import settings

CONTENT_TYPE_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def build_photo_key(*, property_id: uuid.UUID, content_type: str) -> str:
    ext = CONTENT_TYPE_TO_EXT.get(content_type)
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported content_type {content_type!r}; "
            f"allowed: {sorted(CONTENT_TYPE_TO_EXT)}",
        )
    return f"properties/{property_id}/photos/{uuid.uuid4()}.{ext}"


class Storage(Protocol):
    async def upload(self, *, key: str, data: bytes, content_type: str) -> str: ...
    async def delete(self, *, url: str) -> None: ...


class LocalStorage:
    def __init__(self, root: str, public_url: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._public_url = public_url.rstrip("/")

    async def upload(self, *, key: str, data: bytes, content_type: str) -> str:
        path = self._root / key

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(_write)
        return f"{self._public_url}/{key}"

    async def delete(self, *, url: str) -> None:
        prefix = f"{self._public_url}/"
        if not url.startswith(prefix):
            return
        key = url[len(prefix):]
        path = self._root / key
        await asyncio.to_thread(lambda: path.unlink(missing_ok=True))


class S3Storage:
    def __init__(self) -> None:
        import boto3

        self._client = boto3.client(
            "s3",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
        )
        self._bucket = settings.S3_BUCKET
        self._public_prefix = (
            settings.S3_PUBLIC_URL_PREFIX
            or f"https://{self._bucket}.s3.{settings.AWS_REGION}.amazonaws.com"
        ).rstrip("/")

    async def upload(self, *, key: str, data: bytes, content_type: str) -> str:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return f"{self._public_prefix}/{key}"

    async def delete(self, *, url: str) -> None:
        prefix = f"{self._public_prefix}/"
        if not url.startswith(prefix):
            return
        key = url[len(prefix):]
        await asyncio.to_thread(
            self._client.delete_object, Bucket=self._bucket, Key=key
        )


_singleton: Storage | None = None


def get_storage() -> Storage:
    global _singleton
    if _singleton is None:
        if settings.STORAGE_BACKEND == "s3":
            if not settings.S3_BUCKET:
                raise RuntimeError("STORAGE_BACKEND=s3 but S3_BUCKET is empty")
            _singleton = S3Storage()
        else:
            _singleton = LocalStorage(
                root=settings.LOCAL_UPLOAD_DIR,
                public_url=settings.STORAGE_PUBLIC_URL,
            )
    return _singleton
