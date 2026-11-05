"""Private record storage; persistent locally, S3-compatible in deployment."""

import asyncio
import os
import tempfile
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from services.platform.config import Settings


class ObjectStore(Protocol):
    async def put(self, key: str, content: bytes, content_type: str) -> str: ...

    async def get(self, uri: str) -> bytes: ...

    async def delete(self, uri: str) -> None: ...


def _key(uri: str, bucket: str) -> str:
    prefix = f"s3://{bucket}/"
    if not uri.startswith(prefix):
        raise ValueError("object is outside the configured bucket")
    key = uri[len(prefix) :]
    if not key or any(part in {"", ".", ".."} for part in key.split("/")) or "\\" in key:
        raise ValueError("invalid object key")
    return key


@dataclass
class MemoryObjectStore:
    bucket: str = "medpal-records"
    objects: MutableMapping[str, bytes] = field(default_factory=dict)

    async def put(self, key: str, content: bytes, content_type: str) -> str:
        uri = f"s3://{self.bucket}/{key}"
        self.objects[_key(uri, self.bucket)] = content
        return uri

    async def get(self, uri: str) -> bytes:
        return self.objects[_key(uri, self.bucket)]

    async def delete(self, uri: str) -> None:
        self.objects.pop(_key(uri, self.bucket), None)


@dataclass
class FileObjectStore:
    root: Path
    bucket: str = "medpal-records"

    def _path(self, uri: str) -> Path:
        root = self.root.resolve()
        path = (root / _key(uri, self.bucket)).resolve()
        if not path.is_relative_to(root):
            raise ValueError("object is outside the storage root")
        return path

    async def put(self, key: str, content: bytes, content_type: str) -> str:
        uri = f"s3://{self.bucket}/{key}"
        path = self._path(uri)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Publish only complete objects so concurrent reads never see a partial write.
            descriptor, temporary = tempfile.mkstemp(dir=path.parent)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)

        await asyncio.to_thread(write)
        return uri

    async def get(self, uri: str) -> bytes:
        return await asyncio.to_thread(self._path(uri).read_bytes)

    async def delete(self, uri: str) -> None:
        await asyncio.to_thread(self._path(uri).unlink, missing_ok=True)


@dataclass
class S3ObjectStore:
    client: Any
    bucket: str
    encryption: str = "AES256"

    async def put(self, key: str, content: bytes, content_type: str) -> str:
        uri = f"s3://{self.bucket}/{key}"
        _key(uri, self.bucket)
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
            ServerSideEncryption=self.encryption,
        )
        return uri

    async def get(self, uri: str) -> bytes:
        key = _key(uri, self.bucket)

        def read() -> bytes:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            try:
                return bytes(body.read())
            finally:
                body.close()

        return await asyncio.to_thread(read)

    async def delete(self, uri: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=_key(uri, self.bucket))


def build_object_store(settings: Settings) -> ObjectStore:
    if settings.object_store_backend == "memory":
        return MemoryObjectStore(settings.object_store_bucket)
    if settings.object_store_backend == "file":
        return FileObjectStore(Path(settings.object_store_directory), settings.object_store_bucket)
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=settings.object_store_endpoint_url,
        region_name=settings.object_store_region,
        aws_access_key_id=settings.object_store_access_key_id,
        aws_secret_access_key=settings.object_store_secret_access_key,
        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 3}),
    )
    return S3ObjectStore(client, settings.object_store_bucket)
