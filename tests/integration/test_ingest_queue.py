"""Parallel page ingest and the queue path, on real Postgres."""

import httpx
import psycopg
import pytest

from services.api.main import create_app
from services.platform.auth import AuthContext
from services.records.ingest_graph import job_id
from services.records.service import ingest_record, upload_record
from services.records.storage import FileObjectStore
from services.worker import ingest_document
from tests.unit.test_adapters import pdf_bytes

pytestmark = pytest.mark.integration


def patient(world) -> AuthContext:
    return {"user_id": world["user"], "role": "patient", "acting_for_patient_id": world["patient"]}


async def test_pages_are_processed_in_parallel_and_written_in_order(pool, world, tmp_path, admin_url):
    store = FileObjectStore(tmp_path)
    pages = [f"Page {n}: haemoglobin {10 + n}.{n} g/dL" for n in range(1, 6)]
    uploaded = await upload_record(
        pool,
        store,
        patient(world),
        patient_id=world["patient"],
        filename="cbc.pdf",
        content=pdf_bytes(pages),
        content_type="application/pdf",
    )
    assert await ingest_record(pool, store, doc_id=uploaded.doc_id, max_concurrency=2) == "ready"
    with psycopg.connect(admin_url) as conn:
        rows = conn.execute(
            "SELECT page, ordinal, text FROM doc_chunk WHERE doc_id = %s ORDER BY ordinal", (uploaded.doc_id,)
        ).fetchall()
    assert [r[0] for r in rows] == [1, 2, 3, 4, 5]
    assert [r[1] for r in rows] == [0, 1, 2, 3, 4]
    assert all(f"Page {r[0]}" in r[2] for r in rows)


class FakeQueue:
    def __init__(self):
        self.jobs: list[tuple[str, tuple, dict]] = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args, kwargs))

    async def aclose(self):
        pass


async def test_queue_mode_enqueues_only_the_id_and_the_worker_finishes_the_job(world, tmp_path):
    app = create_app()
    queue = FakeQueue()
    headers = {"X-Dev-User-Id": world["user"], "X-Dev-Role": "patient", "X-Dev-Patient-Id": world["patient"]}
    async with app.router.lifespan_context(app):
        app.state.ingest_queue = queue
        app.state.object_store = FileObjectStore(tmp_path)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            r = await client.post(
                "/api/records",
                headers=headers,
                data={"patient_id": world["patient"]},
                files={"file": ("lipid.pdf", pdf_bytes(["LDL 162 mg/dL"]), "application/pdf")},
            )
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["status"] == "queued"
            [(name, args, kwargs)] = queue.jobs
            assert name == "ingest_document"
            assert args == (body["doc_id"],)  # the id only: no document content goes to Redis
            assert kwargs == {"_job_id": job_id(body["doc_id"])}

            ctx = {"pool": app.state.app_pool, "store": app.state.object_store}
            assert await ingest_document(ctx, body["doc_id"]) == "ready"
            listed = (await client.get("/api/records", headers=headers)).json()
            assert [x["status"] for x in listed if x["doc_id"] == body["doc_id"]] == ["ready"]
