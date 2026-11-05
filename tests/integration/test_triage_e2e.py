"""Triage end to end on real Postgres: API → triage graph → interrupt → resume → appointment + audit.
Also proves the API is stateless: a run paused by one app instance is resumed by another."""

import uuid

import httpx
import psycopg
import pytest

from services.api.main import create_app

pytestmark = pytest.mark.integration


async def _client_call(method_path: str, json: dict, headers: dict) -> httpx.Response:
    app = create_app()  # real Postgres lifespan, fresh instance each call
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://t") as c,
    ):
        return await c.post(method_path, json=json, headers=headers)


async def test_book_across_two_app_instances(gm_world, admin_url):
    headers = {
        "X-Dev-User-Id": gm_world["user"],
        "X-Dev-Role": "patient",
        "X-Dev-Patient-Id": gm_world["patient"],
    }
    r = await _client_call("/triage", {"text": "mild fever and body ache"}, headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "awaiting_safety_check"
    answers = {q["key"]: False for q in body["safety_questions"]}

    # Each step runs on a brand-new app instance: state must come from the Postgres checkpointer.
    r = await _client_call(f"/triage/{body['thread_id']}/resume", {"safety_answers": answers}, headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "awaiting_choice"
    assert gm_world["slot"] in [c["slot_id"] for c in body["candidates"]]

    key = f"key-{uuid.uuid4()}"
    r = await _client_call(
        f"/triage/{body['thread_id']}/resume", {"slot_id": gm_world["slot"], "idempotency_key": key}, headers
    )
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "booked"

    with psycopg.connect(admin_url) as conn:
        appt = conn.execute(
            "SELECT patient_id::text, source FROM appointment WHERE appt_id = %s", (done["booking_id"],)
        ).fetchone()
        audits = conn.execute(
            "SELECT count(*) FROM audit_event WHERE resource = 'appointment' AND record_id = %s",
            (done["booking_id"],),
        ).fetchone()
    assert appt == (gm_world["patient"], "assistant")
    assert audits is not None and audits[0] == 1


async def test_emergency_creates_ticket(gm_world, admin_url):
    headers = {
        "X-Dev-User-Id": gm_world["user"],
        "X-Dev-Role": "patient",
        "X-Dev-Patient-Id": gm_world["patient"],
    }
    r = await _client_call("/triage", {"text": "crushing chest pain since an hour"}, headers)
    body = r.json()
    assert body["status"] == "emergency"
    with psycopg.connect(admin_url) as conn:
        row = conn.execute(
            "SELECT kind, status FROM handoff_ticket WHERE ticket_id = %s", (body["handoff_ticket_id"],)
        ).fetchone()
    assert row == ("emergency", "open")
