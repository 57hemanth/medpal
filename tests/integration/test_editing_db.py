# ruff: noqa: F811  (rx_world is a shared fixture imported from the pharmacy tests)
"""Changing things after the fact, on real Postgres: who may, and what each change leaves behind."""

import uuid

import psycopg
import pytest

from services.pharmacy import service as pharmacy
from services.records.service import delete_record, update_record
from services.records.storage import MemoryObjectStore
from services.scribe.service import ChangeRefused, amend_note, change_prescription, list_notes
from tests.integration.test_pharmacy_db import _auth, _name, _sign, rx_world  # noqa: F401

pytestmark = pytest.mark.integration


def _one(admin_url, sql, *params):
    with psycopg.connect(admin_url) as conn:
        return conn.execute(sql, params).fetchone()


# ---- stock -----------------------------------------------------------------------------------------


async def test_a_pharmacist_counts_receives_and_writes_off_with_every_change_logged(
    pool, admin_url, rx_world
):
    w = rx_world
    me = _auth(w["pharmacist"], "pharmacist")
    assert (
        await pharmacy.adjust_stock(
            pool, me, medicine_id=w["in_stock"], kind="count", qty=3, reason="shelf count"
        )
    )["qty"] == 3
    assert (
        await pharmacy.adjust_stock(
            pool, me, medicine_id=w["in_stock"], kind="delivery", qty=10, reason="invoice 42"
        )
    )["qty"] == 13
    assert (
        await pharmacy.adjust_stock(
            pool, me, medicine_id=w["in_stock"], kind="write_off", qty=2, reason="expired"
        )
    )["qty"] == 11
    with pytest.raises(pharmacy.InvalidChange, match="more than is on hand"):
        await pharmacy.adjust_stock(pool, me, medicine_id=w["in_stock"], kind="write_off", qty=50, reason="x")
    history = await pharmacy.stock_history(pool, me, medicine_id=w["in_stock"])
    assert [(h["kind"], h["qty_before"], h["qty_after"]) for h in history] == [
        ("write_off", 13, 11),
        ("delivery", 3, 13),
        ("count", 5, 3),
    ]
    # The other clinic's pharmacist sees none of it and their own clinic's count is untouched.
    assert (
        await pharmacy.stock_history(pool, _auth(w["pharmacist2"], "pharmacist"), medicine_id=w["in_stock"])
        == []
    )
    assert (
        _one(
            admin_url,
            "SELECT qty FROM medicine_stock WHERE clinic_id = %s AND medicine_id = %s",
            w["clinic"],
            w["in_stock"],
        )[0]
        == 11
    )


async def test_only_pharmacists_adjust_stock_even_calling_the_database_directly(pool, rx_world):
    w = rx_world
    with pytest.raises(pharmacy.NotAllowed):
        await pharmacy.adjust_stock(
            pool,
            _auth(w["doctor_user"], "doctor"),
            medicine_id=w["in_stock"],
            kind="count",
            qty=99,
            reason="x",
        )
    from services.platform.db import scoped

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with scoped(pool, _auth(w["doctor_user"], "doctor")) as conn:
            await conn.execute("SELECT adjust_stock(%s, 'count', 99, 'x')", (w["in_stock"],))


# ---- medicines -------------------------------------------------------------------------------------


async def test_pharmacists_add_and_correct_medicines_and_nobody_else_can(pool, admin_url, rx_world):
    w = rx_world
    me = _auth(w["pharmacist"], "pharmacist")
    added = await pharmacy.add_medicine(
        pool, me, {"name": "Testocet 650", "composition": "Paracetamol (650mg)", "price_inr": 32.5}
    )
    assert added["source"] == "clinic"
    await pharmacy.update_medicine(pool, me, added["medicine_id"], {"pack_size": "strip of 15 tablets"})
    assert (
        _one(admin_url, "SELECT pack_size FROM medicine WHERE medicine_id = %s", added["medicine_id"])[0]
        == "strip of 15 tablets"
    )
    with pytest.raises(pharmacy.NotAllowed):
        await pharmacy.update_medicine(
            pool, _auth(w["doctor_user"], "doctor"), added["medicine_id"], {"name": "x"}
        )
    from services.platform.db import scoped

    async with scoped(pool, _auth(w["doctor_user"], "doctor")) as conn:  # row-level security, not just code
        cursor = await conn.execute(
            "UPDATE medicine SET name = 'x' WHERE medicine_id = %s", (added["medicine_id"],)
        )
        assert cursor.rowcount == 0


# ---- patient records -------------------------------------------------------------------------------


def _document(admin_url, patient, user) -> str:
    doc, chunk = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute(
            "INSERT INTO document (doc_id, patient_id, type, uri, sha256, uploaded_by)"
            " VALUES (%s, %s, 'other', %s, %s, %s)",
            (doc, patient, f"s3://medpal-records/patients/{patient}/records/{doc}", doc, user),
        )
        conn.execute(
            "INSERT INTO doc_chunk (chunk_id, doc_id, patient_id, page, ordinal, text, embedding)"
            " VALUES (%s, %s, %s, 1, 0, 'LDL 130', array_fill(0, ARRAY[1024])::vector)",
            (chunk, doc, patient),
        )
    return doc


async def test_a_patient_renames_retypes_and_deletes_their_own_records_only(pool, admin_url, rx_world):
    w = rx_world
    doc = _document(admin_url, w["patient"], w["patient_user"])
    asha = _auth(w["patient_user"], "patient", w["patient"])
    other = _auth(w["other_user"], "patient", w["other_patient"])
    await update_record(pool, asha, doc_id=doc, title="Lipid profile, March", doc_type="lab_report")
    assert _one(admin_url, "SELECT title, type FROM document WHERE doc_id = %s", doc) == (
        "Lipid profile, March",
        "lab_report",
    )
    with pytest.raises(LookupError):
        await update_record(pool, other, doc_id=doc, title="mine now")
    with pytest.raises(LookupError):
        await delete_record(pool, MemoryObjectStore(), other, doc_id=doc)
    store = MemoryObjectStore(objects={f"patients/{w['patient']}/records/{doc}": b"%PDF"})
    await delete_record(pool, store, asha, doc_id=doc)
    assert _one(admin_url, "SELECT count(*) FROM doc_chunk WHERE doc_id = %s", doc)[0] == 0  # can't be cited
    assert store.objects == {}
    assert (
        _one(admin_url, "SELECT action FROM audit_event WHERE record_id = %s ORDER BY at DESC LIMIT 1", doc)[
            0
        ]
        == "delete"
    )


# ---- prescriptions and notes -----------------------------------------------------------------------


async def _rx(pool, admin_url, w, medicine_key):
    await _sign(pool, admin_url, w, w["patient"], [_name(w, medicine_key)])
    return _one(
        admin_url,
        "SELECT rx_id::text FROM prescription WHERE patient_id = %s AND medicine_id = %s"
        " ORDER BY created_at DESC LIMIT 1",
        w["patient"],
        w[medicine_key],
    )[0]


async def test_stopping_a_prescription_releases_the_hold_and_tells_the_patient(pool, admin_url, rx_world):
    w = rx_world
    rx = await _rx(pool, admin_url, w, "in_stock")
    await change_prescription(
        pool, _auth(w["doctor_user"], "doctor"), rx_id=rx, reason="rash after first dose"
    )
    assert _one(admin_url, "SELECT status, stop_reason FROM prescription WHERE rx_id = %s", rx) == (
        "stopped",
        "rash after first dose",
    )
    assert _one(admin_url, "SELECT status FROM medicine_reservation WHERE rx_id = %s", rx)[0] == "released"
    body = _one(
        admin_url,
        "SELECT body FROM patient_notification WHERE patient_id = %s AND kind = 'prescription_changed'",
        w["patient"],
    )[0]
    assert "stopped" in body
    with pytest.raises(ChangeRefused):
        await change_prescription(pool, _auth(w["doctor_user"], "doctor"), rx_id=rx, reason="again")


async def test_replacing_a_prescription_holds_the_new_medicine_and_links_the_old(pool, admin_url, rx_world):
    w = rx_world
    rx = await _rx(pool, admin_url, w, "in_stock")
    out = await change_prescription(
        pool, _auth(w["doctor_user"], "doctor"), rx_id=rx, reason="switch", replacement=_name(w, "last_pack")
    )
    new = out["replacement_rx_id"]
    assert _one(admin_url, "SELECT replaces_rx_id::text, status FROM prescription WHERE rx_id = %s", new) == (
        rx,
        "active",
    )
    assert _one(admin_url, "SELECT status FROM medicine_reservation WHERE rx_id = %s", new)[0] == "reserved"


async def test_only_the_prescribing_doctor_changes_a_prescription(pool, admin_url, rx_world):
    w = rx_world
    rx = await _rx(pool, admin_url, w, "in_stock")
    other_doctor, other_user = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute(
            "INSERT INTO doctor (doctor_id, name, specialty_id) SELECT %s, 'Dr Other', specialty_id"
            " FROM doctor WHERE doctor_id = %s",
            (other_doctor, w["doctor"]),
        )
        conn.execute(
            "INSERT INTO app_user (user_id, role, doctor_id) VALUES (%s, 'doctor', %s)",
            (other_user, other_doctor),
        )
    with pytest.raises((PermissionError, LookupError)):
        await change_prescription(pool, _auth(other_user, "doctor"), rx_id=rx, reason="not mine")
    assert _one(admin_url, "SELECT status FROM prescription WHERE rx_id = %s", rx)[0] == "active"


async def test_amending_a_note_adds_a_version_and_keeps_the_signed_one(pool, admin_url, rx_world):
    w = rx_world
    await _sign(pool, admin_url, w, w["patient"], [])
    doctor = _auth(w["doctor_user"], "doctor")
    note_id = _one(
        admin_url,
        "SELECT note_id::text FROM note_version WHERE patient_id = %s ORDER BY signed_at DESC LIMIT 1",
        w["patient"],
    )[0]
    signed = await amend_note(
        pool, doctor, note_id=note_id, soap={"plan": "Review in 2 weeks"}, reason="follow-up interval missed"
    )
    assert signed.version == 2
    assert (
        _one(
            admin_url,
            "SELECT soap_json->>'plan' FROM note_version WHERE note_id = %s AND version = 1",
            note_id,
        )[0]
        == "p"
    )
    [note] = [n for n in await list_notes(pool, doctor) if n["note_id"] == note_id]
    assert note["version"] == 2 and note["soap_json"]["plan"] == "Review in 2 weeks"
    assert note["earlier_versions"][0]["version"] == 1 and note["mine"] is True
    assert note["edit_history"][-1]["reason"] == "follow-up interval missed"
    with pytest.raises(ChangeRefused):
        await amend_note(
            pool, doctor, note_id=note_id, soap={"plan": "Review in 2 weeks"}, reason="no change"
        )
    with pytest.raises(PermissionError):
        await amend_note(
            pool,
            _auth(w["patient_user"], "patient", w["patient"]),
            note_id=note_id,
            soap={"plan": "x"},
            reason="patient edit",
        )
