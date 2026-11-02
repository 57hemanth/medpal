"""Slice 0 end to end on real Postgres: API → W1 graph → interrupt → resume → appointment + audit.
Also proves the API is stateless: a run paused by one app instance is resumed by another."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest

from services.api.main import create_app
from services.platform.config import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture
def gm_world() -> dict[str, str]:
    """A fresh General Medicine doctor with the earliest slot, so the stub specialty finds it first."""
    ids = {k: str(uuid.uuid4()) for k in ("clinic", "doctor", "slot", "patient", "user")}
    with psycopg.connect(get_settings().database_url) as conn, conn.transaction():
        conn.execute("INSERT INTO specialty (name) VALUES ('General Medicine') ON CONFLICT (name) DO NOTHING")
        spec = conn.execute("SELECT specialty_id FROM specialty WHERE name = 'General Medicine'").fetchone()
        assert spec is not None
        conn.execute(
            "INSERT INTO clinic (clinic_id, name, city, district, opens_at, closes_at)"
            " VALUES (%s, 'E2E Clinic', 'Pune', 'Pune', '09:00', '18:00')",
            (ids["clinic"],),
        )
        conn.execute(
            "INSERT INTO doctor (doctor_id, name, specialty_id) VALUES (%s, 'Dr E2E', %s)",
            (ids["doctor"], spec[0]),
        )
        conn.execute(
            "INSERT INTO slot (slot_id, doctor_id, clinic_id, starts_at) VALUES (%s, %s, %s, %s)",
            (ids["slot"], ids["doctor"], ids["clinic"], datetime.now(UTC) + timedelta(minutes=2)),
        )
        conn.execute("INSERT INTO patient (patient_id, name) VALUES (%s, 'E2E Patient')", (ids["patient"],))
        conn.execute(
            "INSERT INTO app_user (user_id, role, patient_id) VALUES (%s, 'patient', %s)",
            (ids["user"], ids["patient"]),
        )
    return ids


async def _client_call(method_path: str, json: dict, headers: dict) -> httpx.Response:
    app = create_app()  # real Postgres lifespan, fresh instance each call
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://t") as c,
    ):
        return await c.post(method_path, json=json, headers=headers)


async def test_book_across_two_app_instances(gm_world):
    headers = {
        "X-Dev-User-Id": gm_world["user"],
        "X-Dev-Role": "patient",
        "X-Dev-Patient-Id": gm_world["patient"],
    }
    r = await _client_call("/triage", {"text": "mild fever and body ache"}, headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "awaiting_choice"
    assert gm_world["slot"] in [c["slot_id"] for c in body["candidates"]]

    # Resume on a brand-new app instance: state must come from the Postgres checkpointer.
    key = f"key-{uuid.uuid4()}"
    r = await _client_call(
        f"/triage/{body['thread_id']}/resume", {"slot_id": gm_world["slot"], "idempotency_key": key}, headers
    )
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "booked"

    with psycopg.connect(get_settings().database_url) as conn:
        appt = conn.execute(
            "SELECT patient_id::text, source FROM appointment WHERE appt_id = %s", (done["booking_id"],)
        ).fetchone()
        audits = conn.execute(
            "SELECT count(*) FROM audit_event WHERE resource = 'appointment' AND record_id = %s",
            (done["booking_id"],),
        ).fetchone()
    assert appt == (gm_world["patient"], "assistant")
    assert audits is not None and audits[0] == 1


async def test_emergency_creates_ticket(gm_world):
    headers = {
        "X-Dev-User-Id": gm_world["user"],
        "X-Dev-Role": "patient",
        "X-Dev-Patient-Id": gm_world["patient"],
    }
    r = await _client_call("/triage", {"text": "crushing chest pain since an hour"}, headers)
    body = r.json()
    assert body["status"] == "emergency"
    with psycopg.connect(get_settings().database_url) as conn:
        row = conn.execute(
            "SELECT kind, status FROM handoff_ticket WHERE ticket_id = %s", (body["handoff_ticket_id"],)
        ).fetchone()
    assert row == ("emergency", "open")
