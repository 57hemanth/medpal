"""Operations endpoints behind the product dashboards: appointment filters and the compliance audit log."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest

from services.api.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def ops_world(world, admin_url):
    """One future booked appointment, one past one, a desk user and a compliance user."""
    desk, compliance, past_slot = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    future_appt, past_appt = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute(
            "INSERT INTO app_user (user_id, role) VALUES (%s, 'desk'), (%s, 'compliance')", (desk, compliance)
        )
        conn.execute(
            "INSERT INTO slot (slot_id, doctor_id, clinic_id, starts_at, capacity)"
            " VALUES (%s, %s, %s, %s, 1)",
            (past_slot, world["doctor"], world["clinic"], datetime.now(UTC) - timedelta(days=3)),
        )
        for appt, slot in ((future_appt, world["slot"]), (past_appt, past_slot)):
            conn.execute(
                "INSERT INTO appointment (appt_id, patient_id, slot_id, status, source, idempotency_key,"
                " created_by) VALUES (%s, %s, %s, 'booked', 'desk', %s, %s)",
                (appt, world["patient"], slot, f"ops-{appt}", desk),
            )
        conn.execute(
            "INSERT INTO audit_event (actor_id, actor_role, action, resource, record_id, patient_id, purpose)"
            " VALUES (%s, 'desk', 'cancel', 'appointment', %s, %s, 'test')",
            (desk, past_appt, world["patient"]),
        )
    return {**world, "desk": desk, "compliance": compliance, "future": future_appt, "past": past_appt}


async def _get(path: str, headers: dict[str, str], **params: object) -> httpx.Response:
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
    ):
        return await client.get(path, headers=headers, params=params)


async def test_upcoming_and_past_appointments_are_filtered_with_names_for_the_desk(ops_world):
    desk = {"X-Dev-User-Id": ops_world["desk"], "X-Dev-Role": "desk"}
    upcoming = (await _get("/api/appointments", desk, when="upcoming")).json()
    past = (await _get("/api/appointments", desk, when="past")).json()
    ids_up, ids_past = {a["appt_id"] for a in upcoming}, {a["appt_id"] for a in past}
    assert ops_world["future"] in ids_up and ops_world["past"] not in ids_up
    assert ops_world["past"] in ids_past and ops_world["future"] not in ids_past
    row = next(a for a in upcoming if a["appt_id"] == ops_world["future"])
    assert row["patient_name"] and row["specialty"] == ops_world["specialty_name"]


async def test_patient_sees_only_their_own_appointments(ops_world):
    patient = {
        "X-Dev-User-Id": ops_world["user"],
        "X-Dev-Role": "patient",
        "X-Dev-Patient-Id": ops_world["patient"],
    }
    rows = (await _get("/api/appointments", patient, when="all")).json()
    assert rows and {a["patient_id"] for a in rows} == {ops_world["patient"]}


async def test_audit_log_is_compliance_only_and_filterable(ops_world):
    compliance = {"X-Dev-User-Id": ops_world["compliance"], "X-Dev-Role": "compliance"}
    desk = {"X-Dev-User-Id": ops_world["desk"], "X-Dev-Role": "desk"}
    assert (await _get("/api/audit", desk)).status_code == 403
    r = await _get("/api/audit", compliance, resource="appointment", patient_id=ops_world["patient"])
    assert r.status_code == 200
    events = r.json()
    assert [e["record_id"] for e in events] == [ops_world["past"]]
    assert events[0]["action"] == "cancel" and events[0]["patient_name"]
