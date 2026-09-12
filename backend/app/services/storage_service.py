"""
StorageService — S3 operations for market data, model artifacts, reports.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageService:

    @staticmethod
    def _client():
        import boto3
        return boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )

    @staticmethod
    async def upload_bytes(data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
        import asyncio
        loop = asyncio.get_event_loop()
        client = StorageService._client()

        def _upload():
            client.put_object(
                Bucket=settings.S3_BUCKET_NAME,
                Key=key,
                Body=data,
                ContentType=content_type,
            )

        await loop.run_in_executor(None, _upload)
        logger.debug(f"Uploaded {len(data)} bytes to s3://{settings.S3_BUCKET_NAME}/{key}")
        return f"s3://{settings.S3_BUCKET_NAME}/{key}"

    @staticmethod
    async def download_bytes(key: str) -> bytes:
        import asyncio
        loop = asyncio.get_event_loop()
        client = StorageService._client()

        def _download():
            response = client.get_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
            return response["Body"].read()

        return await loop.run_in_executor(None, _download)

    @staticmethod
    async def generate_presigned_url(key: str, expires_in: int = 3600) -> str:
        import asyncio
        loop = asyncio.get_event_loop()
        client = StorageService._client()

        def _presign():
            return client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.S3_BUCKET_NAME, "Key": key},
                ExpiresIn=expires_in,
            )

        return await loop.run_in_executor(None, _presign)

    @staticmethod
    async def delete(key: str) -> None:
        import asyncio
        loop = asyncio.get_event_loop()
        client = StorageService._client()
        await loop.run_in_executor(None, lambda: client.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=key))
