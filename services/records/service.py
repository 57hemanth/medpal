"""Records upload, ingest status and chunk creation."""

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any, cast

from psycopg import AsyncCursor
from psycopg_pool import AsyncConnectionPool

from services.platform import audit
from services.platform.auth import AuthContext
from services.platform.db import scoped

from .ingest import validate_upload
from .storage import ObjectStore


async def _one(cur: AsyncCursor[Any]) -> dict[str, Any]:
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError("expected row")
    return cast(dict[str, Any], row)


@dataclass(frozen=True)
class UploadedRecord:
    doc_id: str
    job_id: str
    status: str
    sha256: str


async def upload_record(
    pool: AsyncConnectionPool,
    store: ObjectStore,
    auth: AuthContext,
    *,
    patient_id: str,
    filename: str,
    content: bytes,
    content_type: str,
) -> UploadedRecord:
    if auth["acting_for_patient_id"] != patient_id:
        raise PermissionError("cannot upload for a different patient")
    await asyncio.to_thread(validate_upload, content, content_type)
    digest = hashlib.sha256(content).hexdigest()
    key = f"patients/{patient_id}/records/{digest}"
    uri = await store.put(key, content, content_type)
    async with scoped(pool, auth) as conn:
        await conn.execute(
            "INSERT INTO document (patient_id, type, uri, sha256, uploaded_by)"
            " VALUES (%s, 'other', %s, %s, %s)"
            " ON CONFLICT (patient_id, sha256) DO NOTHING",
            (patient_id, uri, digest, auth["user_id"]),
        )
        doc = await _one(
            await conn.execute(
                "SELECT doc_id::text, sha256 FROM document WHERE patient_id = %s AND sha256 = %s",
                (patient_id, digest),
            )
        )
        job = await _one(
            await conn.execute(
                "INSERT INTO ingest_job (doc_id, status) VALUES (%s, 'queued')"
                " RETURNING job_id::text, status",
                (doc["doc_id"],),
            )
        )
        await audit.write(
            conn,
            auth,
            action="upload",
            resource="document",
            record_id=doc["doc_id"],
            patient_id=patient_id,
            purpose="records upload",
        )
    return UploadedRecord(doc_id=doc["doc_id"], job_id=job["job_id"], status=job["status"], sha256=digest)


async def ingest_record(
    pool: AsyncConnectionPool, store: ObjectStore, *, doc_id: str, max_concurrency: int = 4
) -> str:
    """Extract, chunk, embed and index one document; pages are processed in parallel (ingest_graph)."""
    from .ingest_graph import run_ingest  # local import: the graph module imports this package

    return await run_ingest(pool, store, doc_id=doc_id, max_concurrency=max_concurrency)


async def list_records(pool: AsyncConnectionPool, auth: AuthContext) -> list[dict[str, Any]]:
    async with scoped(pool, auth) as conn:
        rows = await (
            await conn.execute(
                "SELECT d.doc_id::text, d.patient_id::text, d.type, d.sha256, d.uploaded_at,"
                " d.phi_status, j.status, j.error"
                " FROM document d LEFT JOIN LATERAL ("
                "   SELECT status, error FROM ingest_job"
                "   WHERE doc_id = d.doc_id ORDER BY created_at DESC LIMIT 1"
                " ) j ON true ORDER BY d.uploaded_at DESC"
            )
        ).fetchall()
    return cast(list[dict[str, Any]], rows)
