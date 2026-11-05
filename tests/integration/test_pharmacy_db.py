"""Pharmacy against real Postgres: reservations at signing, dispensing, and who may see what."""

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from services.pharmacy import service as pharmacy
from services.platform.auth import AuthContext
from services.platform.db import scoped
from services.scribe.service import SoapDraft, list_notes, sign_note

pytestmark = pytest.mark.integration


def _auth(user: str, role: str, patient: str | None = None) -> AuthContext:
    return AuthContext(user_id=user, role=role, acting_for_patient_id=patient)  # type: ignore[typeddict-item]


@pytest.fixture
def rx_world(admin_url):
    """One clinic with a doctor, a pharmacist and stock; a second clinic with its own pharmacist."""
    ids = {
        k: str(uuid.uuid4())
        for k in (
            "clinic",
            "clinic2",
            "specialty",
            "doctor",
            "doctor_user",
            "pharmacist",
            "pharmacist2",
            "patient",
            "patient_user",
            "other_patient",
            "other_user",
            "in_stock",
            "last_pack",
            "none_left",
        )
    }
    tag = ids["clinic"][:8]
    with psycopg.connect(admin_url) as conn, conn.transaction():
        for clinic, name in ((ids["clinic"], f"Rx Clinic {tag}"), (ids["clinic2"], f"Other Clinic {tag}")):
            conn.execute(
                "INSERT INTO clinic (clinic_id, name, city, district, opens_at, closes_at)"
                " VALUES (%s, %s, 'Pune', 'Pune', '09:00', '18:00')",
                (clinic, name),
            )
        conn.execute(
            "INSERT INTO specialty (specialty_id, name) VALUES (%s, %s)", (ids["specialty"], f"Spec {tag}")
        )
        conn.execute(
            "INSERT INTO doctor (doctor_id, name, specialty_id) VALUES (%s, %s, %s)",
            (ids["doctor"], f"Dr Rx {tag}", ids["specialty"]),
        )
        for patient, user, name in (
            (ids["patient"], ids["patient_user"], f"Rx Patient {tag}"),
            (ids["other_patient"], ids["other_user"], f"Other Patient {tag}"),
        ):
            conn.execute("INSERT INTO patient (patient_id, name) VALUES (%s, %s)", (patient, name))
            conn.execute(
                "INSERT INTO app_user (user_id, role, patient_id) VALUES (%s, 'patient', %s)", (user, patient)
            )
        conn.execute(
            "INSERT INTO app_user (user_id, role, doctor_id) VALUES (%s, 'doctor', %s)",
            (ids["doctor_user"], ids["doctor"]),
        )
        for user, clinic in ((ids["pharmacist"], ids["clinic"]), (ids["pharmacist2"], ids["clinic2"])):
            conn.execute(
                "INSERT INTO app_user (user_id, role, clinic_id) VALUES (%s, 'pharmacist', %s)",
                (user, clinic),
            )
        for medicine, qty in ((ids["in_stock"], 5), (ids["last_pack"], 1), (ids["none_left"], 0)):
            conn.execute(
                "INSERT INTO medicine (medicine_id, name, composition, therapeutic_class, source)"
                " VALUES (%s, %s, %s, 'Test class', 'test')",
                (medicine, f"Med{medicine[:6]}", f"med{medicine[:6]} 10 mg"),
            )
            conn.execute(
                "INSERT INTO medicine_stock (clinic_id, medicine_id, qty, as_of) VALUES (%s, %s, %s, now())",
                (ids["clinic"], medicine, qty),
            )
    return ids


def _encounter(admin_url, w, patient) -> str:
    slot, appt, encounter = (str(uuid.uuid4()) for _ in range(3))
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute(
            "INSERT INTO slot (slot_id, doctor_id, clinic_id, starts_at, capacity)"
            " VALUES (%s, %s, %s, %s, 1)",
            (slot, w["doctor"], w["clinic"], datetime.now(UTC) + timedelta(days=1)),
        )
        conn.execute(
            "INSERT INTO appointment (appt_id, patient_id, slot_id, status, source, idempotency_key,"
            " created_by) VALUES (%s, %s, %s, 'booked', 'desk', %s, %s)",
            (appt, patient, slot, f"rx-{appt}", w["doctor_user"]),
        )
        conn.execute(
            "INSERT INTO encounter (encounter_id, appt_id, patient_id, doctor_id) VALUES (%s, %s, %s, %s)",
            (encounter, appt, patient, w["doctor"]),
        )
    return encounter


async def _sign(pool, admin_url, w, patient, medicines) -> None:
    encounter = _encounter(admin_url, w, patient)
    soap = {"subjective": "s", "objective": "o", "assessment": "a", "plan": "p", "medicines": medicines}
    await sign_note(
        pool,
        _auth(w["doctor_user"], "doctor"),
        encounter_id=encounter,
        draft=SoapDraft(subjective="s", objective="o", assessment="a", plan="p"),
        edited_soap=soap,
        medicines=medicines,
        transcript="Doctor: take the medicine as discussed.",
    )


def _name(w, key) -> str:
    return f"Med{w[key][:6]}"


async def test_signing_reserves_what_is_in_stock_and_never_promises_the_last_pack_twice(
    pool, admin_url, rx_world
):
    w = rx_world
    await _sign(
        pool, admin_url, w, w["patient"], [_name(w, "in_stock"), _name(w, "last_pack"), _name(w, "none_left")]
    )
    await _sign(pool, admin_url, w, w["other_patient"], [_name(w, "last_pack")])
    with psycopg.connect(admin_url) as conn:
        held = conn.execute(
            "SELECT medicine_id::text, patient_id::text FROM medicine_reservation WHERE clinic_id = %s",
            (w["clinic"],),
        ).fetchall()
        available = conn.execute(
            "SELECT medicine_available(%s, %s), medicine_available(%s, %s)",
            (w["clinic"], w["in_stock"], w["clinic"], w["last_pack"]),
        ).fetchone()
    assert sorted(held) == sorted([(w["in_stock"], w["patient"]), (w["last_pack"], w["patient"])])
    assert available == (4, 0)  # the second patient's line for the last pack was not held


async def test_only_the_clinics_pharmacist_dispenses_and_the_patient_is_told(pool, admin_url, rx_world):
    w = rx_world
    await _sign(pool, admin_url, w, w["patient"], [_name(w, "in_stock")])
    mine = _auth(w["pharmacist"], "pharmacist")
    other_clinic = _auth(w["pharmacist2"], "pharmacist")
    [item] = await pharmacy.dispensing_queue(pool, mine)
    assert item["patient_name"].startswith("Rx Patient") and item["doctor_name"].startswith("Dr Rx")
    assert await pharmacy.dispensing_queue(pool, other_clinic) == []
    with pytest.raises(LookupError):
        await pharmacy.dispense(pool, other_clinic, reservation_id=item["reservation_id"])
    with pytest.raises(pharmacy.NotAllowed):
        await pharmacy.dispense(
            pool, _auth(w["patient_user"], "patient", w["patient"]), reservation_id=item["reservation_id"]
        )
    await pharmacy.dispense(pool, mine, reservation_id=item["reservation_id"])
    with pytest.raises(LookupError):  # already dispensed
        await pharmacy.dispense(pool, mine, reservation_id=item["reservation_id"])
    with psycopg.connect(admin_url) as conn:
        qty = conn.execute(
            "SELECT qty FROM medicine_stock WHERE clinic_id = %s AND medicine_id = %s",
            (w["clinic"], w["in_stock"]),
        ).fetchone()[0]
    assert qty == 4
    patient = _auth(w["patient_user"], "patient", w["patient"])
    [note] = await pharmacy.notifications(pool, patient)
    assert "ready to collect" in note["body"] and "Rx Clinic" in note["body"]
    assert await pharmacy.notifications(pool, _auth(w["other_user"], "patient", w["other_patient"])) == []


async def test_no_request_role_can_change_stock_counts_directly(pool, admin_url, rx_world):
    w = rx_world
    for auth in (_auth(w["pharmacist"], "pharmacist"), _auth(w["doctor_user"], "doctor")):
        async with scoped(pool, auth) as conn:
            cur = await conn.execute(
                "UPDATE medicine_stock SET qty = 999 WHERE clinic_id = %s", (w["clinic"],)
            )
            assert cur.rowcount == 0  # row-level security: only the feed sync (system) writes counts
    with psycopg.connect(admin_url) as conn:
        assert (
            conn.execute(
                "SELECT max(qty) FROM medicine_stock WHERE clinic_id = %s", (w["clinic"],)
            ).fetchone()[0]
            == 5
        )


async def test_restock_lists_unmet_demand_first(pool, admin_url, rx_world):
    w = rx_world
    await _sign(pool, admin_url, w, w["patient"], [_name(w, "none_left")])
    rows = await pharmacy.clinic_stock(pool, _auth(w["pharmacist"], "pharmacist"))
    first = rows[0]
    assert (
        first["medicine_id"] == w["none_left"] and first["status"] == "out_of_stock" and first["unmet"] == 1
    )


async def test_notes_carry_the_transcript_and_stay_with_their_patient(pool, admin_url, rx_world):
    w = rx_world
    await _sign(pool, admin_url, w, w["patient"], [_name(w, "in_stock")])
    doctor_notes = await list_notes(pool, _auth(w["doctor_user"], "doctor"))
    mine = [n for n in doctor_notes if n["patient_id"] == w["patient"]]
    assert mine and mine[0]["transcript"].startswith("Doctor: take")
    assert mine[0]["prescriptions"][0]["status"] == "reserved"
    patient_notes = await list_notes(pool, _auth(w["patient_user"], "patient", w["patient"]))
    other_notes = await list_notes(pool, _auth(w["other_user"], "patient", w["other_patient"]))
    assert [n["patient_id"] for n in patient_notes] == [w["patient"]]
    assert other_notes == []
