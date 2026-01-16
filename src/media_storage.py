"""
MinIO media storage helper.
"""

from __future__ import annotations

import asyncio
from typing import Optional
from urllib.parse import urlparse

from src.config import settings
from src.logger import logger


_client = None
_bucket_ready = False


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not settings.MINIO_ENDPOINT:
        return None
    try:
        from minio import Minio
    except Exception as exc:
        logger.warning(f"⚠️ MinIO client недоступен: {exc}")
        return None
    _client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE
    )
    return _client


def _ensure_bucket(client) -> None:
    global _bucket_ready
    if _bucket_ready:
        return
    bucket = settings.MINIO_BUCKET
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    _bucket_ready = True


def _build_public_url(object_name: str) -> str:
    if settings.MINIO_PUBLIC_URL:
        base = settings.MINIO_PUBLIC_URL.rstrip("/")
        return f"{base}/{settings.MINIO_BUCKET}/{object_name}"

    endpoint = settings.MINIO_ENDPOINT
    if endpoint and not endpoint.startswith("http"):
        scheme = "https" if settings.MINIO_SECURE else "http"
        endpoint = f"{scheme}://{endpoint}"
    parsed = urlparse(endpoint or "")
    host = parsed.netloc or parsed.path
    return f"{parsed.scheme}://{host}/{settings.MINIO_BUCKET}/{object_name}"


async def upload_file(
    file_path: str,
    object_name: str,
    content_type: Optional[str] = None
) -> Optional[str]:
    client = _get_client()
    if not client:
        return None

    try:
        await asyncio.to_thread(_ensure_bucket, client)
        await asyncio.to_thread(
            client.fput_object,
            settings.MINIO_BUCKET,
            object_name,
            file_path,
            content_type=content_type
        )
        return _build_public_url(object_name)
    except Exception as exc:
        logger.warning(f"⚠️ Не удалось загрузить медиа в MinIO: {exc}")
        return None
