"""The supervisor through the real API: specialists run on real graphs, threads resume on their own
endpoints, every delegation is audited against the supervisor's trace, and the trace spans the children."""

import uuid

import httpx
import psycopg
import pytest

from services.api.main import create_app

pytestmark = pytest.mark.integration


async def test_two_part_message_delegates_audits_traces_and_resumes(world, admin_url):
    patient = {"X-Dev-User-Id": world["user"], "X-Dev-Role": "patient", "X-Dev-Patient-Id": world["patient"]}
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://t") as client,
    ):
        r = await client.post(
            "/api/assistant",
            headers=patient,
            json={"message": "I have had knee pain for a week. Also what was my LDL in the last report?"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        by = {x["specialist"]: x for x in body["results"]}
        assert set(by) == {"triage", "records"}
        assert by["triage"]["status"] == "awaiting_safety_check"
        assert by["records"]["status"] == "insufficient_evidence"  # no reports uploaded yet
        thread = by["triage"]["thread_id"]
        assert thread == by["triage"]["delegation_id"]

        # The delegated triage thread continues on triage's own endpoint, with its ownership check.
        answers = {q["key"]: False for q in by["triage"]["safety_questions"]}
        r = await client.post(f"/triage/{thread}/resume", headers=patient, json={"safety_answers": answers})
        assert r.status_code == 200, r.text
        assert r.json()["status"] in ("awaiting_choice", "front_desk")

    with psycopg.connect(admin_url) as conn:
        audits = conn.execute(
            "SELECT resource, record_id, patient_id::text FROM audit_event"
            " WHERE trace_id = %s AND action = 'delegate' ORDER BY resource",
            (body["trace_id"],),
        ).fetchall()
        spans = {
            row[0]
            for row in conn.execute("SELECT name FROM trace_span WHERE trace_id = %s", (body["trace_id"],))
        }
        stored = " ".join(
            str(v)
            for row in conn.execute("SELECT * FROM trace_span WHERE trace_id = %s", (body["trace_id"],))
            for v in row
        )
    assert [a[0] for a in audits] == ["assistant.records", "assistant.triage"]
    assert ("assistant.triage", thread, world["patient"]) in audits
    # One trace covers the supervisor and the specialist graph it ran.
    assert {"screen", "plan", "delegate", "combine", "intake", "red_flag_rules"} <= spans
    assert "knee" not in stored


async def test_emergency_through_the_assistant_opens_a_ticket(world, admin_url):
    patient = {"X-Dev-User-Id": world["user"], "X-Dev-Role": "patient", "X-Dev-Patient-Id": world["patient"]}
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://t") as client,
    ):
        r = await client.post(
            "/api/assistant",
            headers=patient,
            json={"message": "sudden crushing chest pain and sweating, also what was my LDL?"},
        )
    body = r.json()
    assert body["planned_by"] == "safety" and body["outcome"] == "emergency"
    [only] = body["results"]
    assert only["specialist"] == "triage" and only["handoff_ticket_id"]


async def test_caregiver_cannot_book_through_the_assistant(world, admin_url):
    carer = str(uuid.uuid4())
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute("INSERT INTO app_user (user_id, role) VALUES (%s, 'caregiver')", (carer,))
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://t") as client,
    ):
        r = await client.post(
            "/api/assistant",
            headers={"X-Dev-User-Id": carer, "X-Dev-Role": "caregiver"},
            json={"message": "she has knee pain, please book a doctor"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "front_desk"
    assert r.json()["results"] == []
