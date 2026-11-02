"""Shortlist semantics on real Postgres: earliest FREE slot per doctor, soonest first,
with limit and exclusions."""

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from services.scheduling import service as scheduling

pytestmark = pytest.mark.integration


@pytest.fixture
def specialty_world(admin_url: str) -> dict:
    """One specialty, four doctors; doctor i's slots start i hours from now, every 15 minutes."""
    spec, clinic, booker, patient = (str(uuid.uuid4()) for _ in range(4))
    name = f"Shortlist {spec[:8]}"
    base = datetime.now(UTC) + timedelta(hours=1)
    doctors, slots = [], {}
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute("INSERT INTO specialty (specialty_id, name) VALUES (%s, %s)", (spec, name))
        conn.execute(
            "INSERT INTO clinic (clinic_id, name, city, district, opens_at, closes_at)"
            " VALUES (%s, 'Shortlist clinic', 'Pune', 'Pune', '00:00', '23:59')",
            (clinic,),
        )
        conn.execute("INSERT INTO patient (patient_id, name) VALUES (%s, 'P')", (patient,))
        conn.execute(
            "INSERT INTO app_user (user_id, role, patient_id) VALUES (%s, 'patient', %s)", (booker, patient)
        )
        for i in range(4):
            doc = str(uuid.uuid4())
            doctors.append(doc)
            conn.execute(
                "INSERT INTO doctor (doctor_id, name, specialty_id) VALUES (%s, %s, %s)",
                (doc, f"Dr {i}", spec),
            )
            slots[doc] = []
            for k in range(3):
                sid = str(uuid.uuid4())
                slots[doc].append(sid)
                conn.execute(
                    "INSERT INTO slot (slot_id, doctor_id, clinic_id, starts_at) VALUES (%s, %s, %s, %s)",
                    (sid, doc, clinic, base + timedelta(hours=i, minutes=15 * k)),
                )
        # Doctor 0's first slot is already booked.
        conn.execute(
            "INSERT INTO appointment (patient_id, slot_id, status, source, idempotency_key, created_by)"
            " VALUES (%s, %s, 'booked', 'desk', %s, %s)",
            (patient, slots[doctors[0]][0], f"sl-{uuid.uuid4()}", booker),
        )
    return {"name": name, "doctors": doctors, "slots": slots}


async def test_earliest_free_slot_per_doctor_soonest_first(pool, specialty_world):
    w = specialty_world
    result = await scheduling.shortlist(pool, w["name"])
    assert [c.doctor_id for c in result] == w["doctors"][:3]  # limit 3, soonest doctors first
    assert result[0].slot_id == w["slots"][w["doctors"][0]][1]  # booked slot skipped
    assert result[1].slot_id == w["slots"][w["doctors"][1]][0]
    assert len({c.doctor_id for c in result}) == 3  # one slot per doctor


async def test_excluded_slots_are_skipped(pool, specialty_world):
    w = specialty_world
    first_free = w["slots"][w["doctors"][0]][1]
    result = await scheduling.shortlist(pool, w["name"], exclude_slot_ids=[first_free])
    assert result[0].slot_id == w["slots"][w["doctors"][0]][2]


async def test_unknown_specialty_returns_nothing(pool, specialty_world):
    assert await scheduling.shortlist(pool, "No Such Specialty") == []
