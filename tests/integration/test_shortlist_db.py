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


@pytest.fixture
def two_city_world(admin_url: str) -> dict:
    """Same specialty in Pune and Hyderabad. The Hyderabad doctor has the soonest slot."""
    spec, pune, hyd, patient, user = (str(uuid.uuid4()) for _ in range(5))
    name = f"TwoCity {spec[:8]}"
    base = datetime.now(UTC) + timedelta(hours=1)
    docs = {k: str(uuid.uuid4()) for k in ("hyd_soonest", "pune_en", "pune_mr")}
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute("INSERT INTO specialty (specialty_id, name) VALUES (%s, %s)", (spec, name))
        for cid, city in ((pune, "Pune"), (hyd, "Hyderabad")):
            conn.execute(
                "INSERT INTO clinic (clinic_id, name, city, district, opens_at, closes_at)"
                " VALUES (%s, %s, %s, %s, '00:00', '23:59')",
                (cid, f"{city} clinic", city, city),
            )
        rows = [
            ("hyd_soonest", hyd, ["en", "te"], 0),
            ("pune_en", pune, ["en"], 1),
            ("pune_mr", pune, ["en", "mr"], 2),
        ]
        for key, cid, langs, hours in rows:
            conn.execute(
                "INSERT INTO doctor (doctor_id, name, specialty_id, languages) VALUES (%s, %s, %s, %s)",
                (docs[key], key, spec, langs),
            )
            conn.execute(
                "INSERT INTO slot (doctor_id, clinic_id, starts_at) VALUES (%s, %s, %s)",
                (docs[key], cid, base + timedelta(hours=hours)),
            )
        conn.execute(
            "INSERT INTO patient (patient_id, name, city, language)"
            " VALUES (%s, 'Pune patient', 'Pune', 'mr')",
            (patient,),
        )
        conn.execute(
            "INSERT INTO app_user (user_id, role, patient_id) VALUES (%s, 'patient', %s)", (user, patient)
        )
    return {"name": name, "docs": docs, "patient": patient, "user": user}


async def test_patient_city_filters_and_language_ranks_first(pool, two_city_world):
    w = two_city_world
    auth = {"user_id": w["user"], "role": "patient", "acting_for_patient_id": w["patient"]}
    prefs = await scheduling.patient_preferences(pool, auth, w["patient"])  # read as the caller, under RLS
    assert (prefs.city, prefs.language) == ("Pune", "mr")
    result = await scheduling.shortlist(pool, w["name"], preferences=prefs)
    # The Hyderabad doctor (soonest overall) is excluded;
    # the Marathi speaker outranks an earlier English-only slot.
    assert [c.doctor_id for c in result] == [w["docs"]["pune_mr"], w["docs"]["pune_en"]]


async def test_preferences_are_not_readable_for_another_patient(pool, two_city_world, world):
    other = {"user_id": world["user"], "role": "patient", "acting_for_patient_id": world["patient"]}
    prefs = await scheduling.patient_preferences(pool, other, two_city_world["patient"])
    assert prefs == scheduling.PatientPreferences()  # RLS hides the row: nothing leaks, defaults apply


async def test_one_doctors_times_skip_booked_and_excluded_slots(pool, specialty_world):
    w = specialty_world
    doctor = w["doctors"][0]
    times = await scheduling.doctor_times(pool, doctor, exclude_slot_ids=[w["slots"][doctor][2]])
    assert [c.slot_id for c in times] == [w["slots"][doctor][1]]  # [0] is booked, [2] excluded
    assert {c.doctor_id for c in times} == {doctor}


async def test_a_time_window_narrows_both_queries(pool, specialty_world):
    w = specialty_world
    # Starting after doctor 1's slots: doctors 0 and 1 drop out of the shortlist.
    later = datetime.now(UTC) + timedelta(hours=3, minutes=1)
    result = await scheduling.shortlist(pool, w["name"], window=scheduling.TimeWindow(start=later))
    assert [c.doctor_id for c in result] == w["doctors"][2:]
    ended = scheduling.TimeWindow(end=datetime.now(UTC))
    assert await scheduling.doctor_times(pool, w["doctors"][3], window=ended) == []
