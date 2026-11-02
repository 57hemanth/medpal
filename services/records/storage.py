"""Object storage boundary for uploaded records.

Production uses S3-compatible storage. Tests use the in-memory implementation; no workflow writes
clinical files to the local filesystem.
"""

from collections.abc import MutableMapping
from dataclasses import dataclass, field
from typing import Protocol


class ObjectStore(Protocol):
    async def put(self, key: str, content: bytes, content_type: str) -> str: ...

    async def get(self, uri: str) -> bytes: ...


@dataclass
class MemoryObjectStore:
    bucket: str = "medpal-records"
    objects: MutableMapping[str, bytes] = field(default_factory=dict)

    async def put(self, key: str, content: bytes, content_type: str) -> str:
        del content_type
        self.objects[key] = content
        return f"s3://{self.bucket}/{key}"

    async def get(self, uri: str) -> bytes:
        key = uri.removeprefix(f"s3://{self.bucket}/")
        return self.objects[key]
