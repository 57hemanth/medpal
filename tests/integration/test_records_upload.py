"""Exercise the real upload-to-retrieval path with the non-superuser database role."""

from services.platform.auth import AuthContext
from services.platform.db import scoped
from services.records.service import ingest_record, upload_record
from services.records.storage import FileObjectStore
from tests.unit.test_adapters import pdf_bytes


async def test_pdf_upload_is_persistent_page_aware_and_retry_safe(pool, world, tmp_path):
    auth = AuthContext(user_id=world["user"], role="patient", acting_for_patient_id=world["patient"])
    store = FileObjectStore(tmp_path)
    content = pdf_bytes(["LDL 162 mg/dL", "HbA1c 6.8 percent"])
    uploaded = await upload_record(
        pool,
        store,
        auth,
        patient_id=world["patient"],
        filename="report.pdf",
        content=content,
        content_type="application/pdf",
    )
    recreated = FileObjectStore(tmp_path)
    assert await ingest_record(pool, recreated, doc_id=uploaded.doc_id) == "ready"
    duplicate = await upload_record(
        pool,
        recreated,
        auth,
        patient_id=world["patient"],
        filename="other-name.pdf",
        content=content,
        content_type="application/pdf",
    )
    assert duplicate.doc_id == uploaded.doc_id
    assert await ingest_record(pool, recreated, doc_id=duplicate.doc_id) == "ready"
    async with scoped(pool, auth) as conn:
        chunks = await (
            await conn.execute(
                "SELECT page, text FROM doc_chunk WHERE doc_id = %s ORDER BY page",
                (uploaded.doc_id,),
            )
        ).fetchall()
    assert [chunk["page"] for chunk in chunks] == [1, 2]
    assert "LDL 162" in chunks[0]["text"]
    assert "HbA1c 6.8" in chunks[1]["text"]
