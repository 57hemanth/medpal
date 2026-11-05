"""Scribe on real Postgres: encounter ownership, stock flags, signing note + prescriptions atomically."""

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from services.agent.scribe.tools import PgScribeTools
from services.platform.auth import AuthContext
from services.platform.db import scoped
from services.platform.egress.client import EgressChatClient
from services.platform.egress.providers import FakeChatModel
from services.scribe.encounters import list_consultations, start_encounter
from services.scribe.service import AlreadySigned, SoapDraft
from services.scribe.stock import PostgresStockSource

pytestmark = pytest.mark.integration


def _id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def clinic_world(admin_url: str) -> dict[str, str]:
    w = {
        k: _id()
        for k in (
            "clinic",
            "spec",
            "doc_a",
            "doc_b",
            "user_a",
            "user_b",
            "patient",
            "puser",
            "pharm",
            "slot",
            "appt",
            "atorva",
            "metformin",
            "amlo",
        )
    }
    now = datetime.now(UTC)
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute(
            "INSERT INTO clinic (clinic_id, name, city, district, opens_at, closes_at)"
            " VALUES (%s, 'Scribe clinic', 'Pune', 'Pune', '08:00', '20:00')",
            (w["clinic"],),
        )
        conn.execute(
            "INSERT INTO specialty (specialty_id, name) VALUES (%s, %s)", (w["spec"], f"S {w['spec'][:8]}")
        )
        for doc, user in (("doc_a", "user_a"), ("doc_b", "user_b")):
            conn.execute(
                "INSERT INTO doctor (doctor_id, name, specialty_id) VALUES (%s, %s, %s)",
                (w[doc], f"Dr {doc}", w["spec"]),
            )
            conn.execute(
                "INSERT INTO app_user (user_id, role, doctor_id) VALUES (%s, 'doctor', %s)", (w[user], w[doc])
            )
        conn.execute("INSERT INTO patient (patient_id, name) VALUES (%s, 'Scribe Patient')", (w["patient"],))
        conn.execute(
            "INSERT INTO app_user (user_id, role, patient_id) VALUES (%s, 'patient', %s)",
            (w["puser"], w["patient"]),
        )
        conn.execute("INSERT INTO app_user (user_id, role) VALUES (%s, 'pharmacist')", (w["pharm"],))
        conn.execute(
            "INSERT INTO slot (slot_id, doctor_id, clinic_id, starts_at) VALUES (%s, %s, %s, %s)",
            (w["slot"], w["doc_a"], w["clinic"], now + timedelta(hours=1)),
        )
        conn.execute(
            "INSERT INTO appointment (appt_id, patient_id, slot_id, status, source, idempotency_key,"
            " created_by) VALUES (%s, %s, %s, 'booked', 'desk', %s, %s)",
            (w["appt"], w["patient"], w["slot"], f"sc-{w['appt']}", w["puser"]),
        )
        for key, name, qty, age in (
            ("atorva", f"Atorvastatin{w['atorva'][:4]}", 40, 2),
            ("metformin", f"Metformin{w['metformin'][:4]}", 0, 2),
            ("amlo", f"Amlodipine{w['amlo'][:4]}", 50, 72),
        ):
            w[f"{key}_name"] = name
            conn.execute(
                "INSERT INTO medicine (medicine_id, name, composition) VALUES (%s, %s, %s)",
                (w[key], name, f"{name.lower()} 10 mg"),
            )
            conn.execute(
                "INSERT INTO medicine_stock (clinic_id, medicine_id, qty, as_of) VALUES (%s, %s, %s, %s)",
                (w["clinic"], w[key], qty, now - timedelta(hours=age)),
            )
    return w


def doctor(w, who="user_a") -> AuthContext:
    return {"user_id": w[who], "role": "doctor", "acting_for_patient_id": None}


async def test_only_the_appointments_doctor_can_start_and_starting_is_idempotent(pool, clinic_world):
    w = clinic_world
    first = await start_encounter(pool, doctor(w), appt_id=w["appt"])
    assert await start_encounter(pool, doctor(w), appt_id=w["appt"]) == first
    with pytest.raises(PermissionError):
        await start_encounter(pool, doctor(w, "user_b"), appt_id=w["appt"])
    listed = await list_consultations(pool, doctor(w))
    assert [(c["appt_id"], c["encounter_id"], c["signed"]) for c in listed] == [(w["appt"], first, False)]
    assert await list_consultations(pool, doctor(w, "user_b")) == []


async def test_stock_flags_are_real_and_carry_freshness(pool, clinic_world):
    w = clinic_world
    encounter = await start_encounter(pool, doctor(w), appt_id=w["appt"])
    flags = await PostgresStockSource(pool).flags(
        doctor(w),
        encounter_id=encounter,
        medicines=[w["atorva_name"], w["metformin_name"], w["amlo_name"], "Unobtainium"],
    )
    assert [f.status for f in flags] == ["in_stock", "out_of_stock", "stale", "not_in_formulary"]
    assert flags[0].qty == 40 and flags[0].as_of is not None
    with pytest.raises(PermissionError):  # another doctor cannot even see the encounter's clinic stock
        await PostgresStockSource(pool).flags(doctor(w, "user_b"), encounter_id=encounter, medicines=["x"])


async def test_signing_writes_note_and_prescriptions_once(pool, clinic_world, admin_url):
    w = clinic_world
    encounter = await start_encounter(pool, doctor(w), appt_id=w["appt"])
    tools = PgScribeTools(pool, EgressChatClient(FakeChatModel()))
    draft = SoapDraft(subjective="s", objective="o", assessment="a", plan="p")
    soap = {
        "subjective": "s",
        "objective": "o",
        "assessment": "a",
        "plan": "statin",
        "medicines": [w["atorva_name"], "Unlisted drug"],
    }
    signed = await tools.sign(
        doctor(w),
        encounter_id=encounter,
        draft=draft,
        soap=soap,
        edit_history=[{"action": "sign"}],
        medicines=soap["medicines"],
    )
    with psycopg.connect(admin_url) as conn:
        rx = conn.execute(
            "SELECT medicine_text, medicine_id::text, substitute_ok FROM prescription WHERE note_id = %s"
            " ORDER BY medicine_text",
            (signed["note_id"],),
        ).fetchall()
    assert rx == [(w["atorva_name"], w["atorva"], False), ("Unlisted drug", None, False)]
    with pytest.raises(AlreadySigned):
        await tools.sign(
            doctor(w), encounter_id=encounter, draft=draft, soap=soap, edit_history=[], medicines=[]
        )
    patient: AuthContext = {"user_id": w["puser"], "role": "patient", "acting_for_patient_id": w["patient"]}
    pharmacist: AuthContext = {"user_id": w["pharm"], "role": "pharmacist", "acting_for_patient_id": None}
    for who in (patient, pharmacist):
        async with scoped(pool, who) as conn:
            n = await (
                await conn.execute(
                    "SELECT count(*) AS n FROM prescription WHERE note_id = %s", (signed["note_id"],)
                )
            ).fetchone()
        assert n["n"] == 2  # type: ignore[index]
