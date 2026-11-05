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


DOCUMENT_TYPES = ("lab_report", "radiology", "prescription", "discharge", "other")


def _title_from(filename: str) -> str | None:
    """'CBC report - March.pdf' -> 'CBC report - March'. A name the patient recognises, nothing more."""
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0].strip()
    return stem[:120] or None


async def upload_record(
    pool: AsyncConnectionPool,
    store: ObjectStore,
    auth: AuthContext,
    *,
    patient_id: str,
    filename: str,
    content: bytes,
    content_type: str,
    doc_type: str = "other",  # lab_report, radiology, prescription, discharge or other
) -> UploadedRecord:
    if auth["acting_for_patient_id"] != patient_id:
        raise PermissionError("cannot upload for a different patient")
    await asyncio.to_thread(validate_upload, content, content_type)
    digest = hashlib.sha256(content).hexdigest()
    key = f"patients/{patient_id}/records/{digest}"
    uri = await store.put(key, content, content_type)
    async with scoped(pool, auth) as conn:
        await conn.execute(
            "INSERT INTO document (patient_id, type, uri, sha256, uploaded_by, title)"
            " VALUES (%s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (patient_id, sha256) DO NOTHING",
            (patient_id, doc_type, uri, digest, auth["user_id"], _title_from(filename)),
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
                "SELECT d.doc_id::text, d.patient_id::text, d.type, d.title, d.sha256, d.uploaded_at,"
                " d.phi_status, j.status, j.error"
                " FROM document d LEFT JOIN LATERAL ("
                "   SELECT status, error FROM ingest_job"
                "   WHERE doc_id = d.doc_id ORDER BY created_at DESC LIMIT 1"
                " ) j ON true ORDER BY d.uploaded_at DESC"
            )
        ).fetchall()
    return cast(list[dict[str, Any]], rows)


@dataclass(frozen=True)
class RecordFile:
    content: bytes
    media_type: str
    filename: str


async def open_record(
    pool: AsyncConnectionPool, store: ObjectStore, auth: AuthContext, *, doc_id: str
) -> RecordFile:
    """The original document, for someone row-level security lets read it. Every view is audited.

    Raises LookupError when the record doesn't exist or isn't visible to the caller: the two look the
    same from outside, so an id can't be probed.
    """
    async with scoped(pool, auth) as conn:
        cur = await conn.execute(
            "SELECT uri, patient_id::text, type FROM document WHERE doc_id = %s", (doc_id,)
        )
        row = cast(dict[str, Any] | None, await cur.fetchone())
        if row is None:
            raise LookupError("record not found")
        await audit.write(
            conn,
            auth,
            action="read",
            resource="document",
            record_id=doc_id,
            patient_id=row["patient_id"],
            purpose="record view",
        )
    content = await store.get(row["uri"])
    is_pdf = content.startswith(b"%PDF")
    return RecordFile(
        content=content,
        media_type="application/pdf" if is_pdf else "text/plain; charset=utf-8",
        filename=f"{row['type']}-{doc_id[:8]}.{'pdf' if is_pdf else 'txt'}",
    )


async def update_record(
    pool: AsyncConnectionPool,
    auth: AuthContext,
    *,
    doc_id: str,
    title: str | None = None,
    doc_type: str | None = None,
) -> dict[str, Any]:
    """Rename or re-type an upload. The patient, or the caregiver who uploaded it (row-level security)."""
    if doc_type is not None and doc_type not in DOCUMENT_TYPES:
        raise ValueError("unknown record type")
    changes: dict[str, Any] = {}
    if title is not None:
        changes["title"] = title.strip()[:120] or None
    if doc_type is not None:
        changes["type"] = doc_type
    if not changes:
        raise ValueError("nothing to change")
    async with scoped(pool, auth) as conn:
        cursor = await conn.execute(
            f"UPDATE document SET {', '.join(f'{k} = %s' for k in changes)}"  # noqa: S608  fixed columns
            " WHERE doc_id = %s RETURNING patient_id::text",
            (*changes.values(), doc_id),
        )
        row = cast(dict[str, Any] | None, await cursor.fetchone())
        if row is None:
            raise LookupError("record not found or not yours to change")
        await audit.write(
            conn,
            auth,
            action="update",
            resource="document",
            record_id=doc_id,
            patient_id=row["patient_id"],
            purpose="rename or re-type record",
        )
    return {"doc_id": doc_id, **changes}


async def delete_record(
    pool: AsyncConnectionPool, store: ObjectStore, auth: AuthContext, *, doc_id: str
) -> None:
    """Delete an upload, its passages (so it can't be searched or cited again) and the stored file."""
    async with scoped(pool, auth) as conn:
        cursor = await conn.execute(
            "DELETE FROM document WHERE doc_id = %s RETURNING uri, patient_id::text", (doc_id,)
        )
        row = cast(dict[str, Any] | None, await cursor.fetchone())
        if row is None:
            raise LookupError("record not found or not yours to delete")
        await audit.write(
            conn,
            auth,
            action="delete",
            resource="document",
            record_id=doc_id,
            patient_id=row["patient_id"],
            purpose="patient deleted record",
        )
    # After the commit: if this fails the row is already gone, and the file is unreachable without it.
    await store.delete(row["uri"])
