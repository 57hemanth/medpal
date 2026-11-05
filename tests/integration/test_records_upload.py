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


async def test_lay_and_hinglish_questions_reach_the_right_page(pool, world, tmp_path):
    """'Sugar' is how people ask; 'glucose' and 'HbA1c' are how reports are written."""
    from services.records.retrieval import retrieve

    auth = AuthContext(user_id=world["user"], role="patient", acting_for_patient_id=world["patient"])
    store = FileObjectStore(tmp_path)
    pages = [
        "Lipid profile. Total cholesterol 238 mg/dL. LDL cholesterol 162 mg/dL. HDL 41 mg/dL.",
        "Diabetes panel. HbA1c 6.8 percent. Fasting plasma glucose 126 mg/dL.",
        "Thyroid and vitamins. TSH 5.9 mIU/L. Vitamin D 18 ng/mL. Vitamin B12 410 pg/mL.",
    ]
    uploaded = await upload_record(
        pool,
        store,
        auth,
        patient_id=world["patient"],
        filename="labs.pdf",
        content=pdf_bytes(pages),
        content_type="application/pdf",
    )
    assert await ingest_record(pool, store, doc_id=uploaded.doc_id) == "ready"
    for question, page in [
        ("mera sugar test ka result kya tha?", 2),
        ("how is my thyroid?", 3),
        ("what was my cholesterol", 1),
    ]:
        top = await retrieve(pool, auth, question=question, patient_id=world["patient"], limit=1)
        assert [c.page for c in top] == [page], question


async def test_a_record_opens_for_its_owner_audited_and_is_invisible_to_others(
    pool, world, admin_url, tmp_path
):
    import uuid

    import httpx
    import psycopg

    from services.api.main import create_app

    other_user, other_patient = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute("INSERT INTO patient (patient_id, name) VALUES (%s, 'Someone Else')", (other_patient,))
        conn.execute(
            "INSERT INTO app_user (user_id, role, patient_id) VALUES (%s, 'patient', %s)",
            (other_user, other_patient),
        )
    owner = {"X-Dev-User-Id": world["user"], "X-Dev-Role": "patient", "X-Dev-Patient-Id": world["patient"]}
    other = {"X-Dev-User-Id": other_user, "X-Dev-Role": "patient", "X-Dev-Patient-Id": other_patient}
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
    ):
        pdf = pdf_bytes(["LDL 162 mg/dL", "HbA1c 6.8 percent"])
        up = await client.post(
            "/api/records",
            headers=owner,
            data={"patient_id": world["patient"]},
            files={"file": ("labs.pdf", pdf, "application/pdf")},
        )
        doc = up.json()["doc_id"]
        mine = await client.get(f"/api/records/{doc}/file", headers=owner)
        theirs = await client.get(f"/api/records/{doc}/file", headers=other)
        missing = await client.get(f"/api/records/{uuid.uuid4()}/file", headers=owner)
        malformed = await client.get("/api/records/not-a-uuid/file", headers=owner)
    assert mine.status_code == 200 and mine.content == pdf
    assert mine.headers["content-type"] == "application/pdf"
    assert mine.headers["cache-control"] == "no-store"
    # Someone else's record and a record that doesn't exist look the same: an id can't be probed.
    assert theirs.status_code == missing.status_code == malformed.status_code == 404
    assert theirs.json() == missing.json()
    with psycopg.connect(admin_url) as conn:
        views = conn.execute(
            "SELECT actor_id::text FROM audit_event WHERE record_id = %s AND purpose = 'record view'", (doc,)
        ).fetchall()
    assert views == [(world["user"],)]
