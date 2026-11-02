"""Row-level security: the access matrix enforced by Postgres, not by application code.

Every query here deliberately OMITS the application-level patient filter, or asks for another
patient's id outright. The database must still return only what the caller is allowed to see.
"""

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from services.platform.auth import AuthContext
from services.platform.config import get_settings
from services.platform.db import scoped, scoped_system
from services.platform.egress import EgressChatClient
from services.platform.egress.providers import FakeChatModel
from services.records.consent import grant_consent, list_consents, revoke_consent
from services.records.qa import answer_question
from services.records.retrieval import retrieve

pytestmark = pytest.mark.integration


def _uuid() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def records_world(admin_url: str) -> dict[str, str]:
    """Two patients with one document and two chunks each, plus one user per role."""
    w = {
        k: _uuid()
        for k in (
            "pa",
            "pb",
            "ua",
            "ub",
            "carer_ok",
            "carer_expired",
            "carer_revoked",
            "doc_user",
            "desk",
            "comp",
            "doctor",
            "clinic",
            "spec",
            "slot",
            "appt",
            "doc_a",
            "doc_b",
        )
    }
    now = datetime.now(UTC)
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute(
            "INSERT INTO clinic (clinic_id, name, city, district, opens_at, closes_at)"
            " VALUES (%s, 'RLS clinic', 'Pune', 'Pune', '09:00', '18:00')",
            (w["clinic"],),
        )
        conn.execute(
            "INSERT INTO specialty (specialty_id, name) VALUES (%s, %s)", (w["spec"], f"RLS {w['spec']}")
        )
        conn.execute(
            "INSERT INTO doctor (doctor_id, name, specialty_id) VALUES (%s, 'Dr RLS', %s)",
            (w["doctor"], w["spec"]),
        )
        for pid, uid, name in ((w["pa"], w["ua"], "Patient A"), (w["pb"], w["ub"], "Patient B")):
            conn.execute("INSERT INTO patient (patient_id, name) VALUES (%s, %s)", (pid, name))
            conn.execute(
                "INSERT INTO app_user (user_id, role, patient_id) VALUES (%s, 'patient', %s)", (uid, pid)
            )
        for uid in (w["carer_ok"], w["carer_expired"], w["carer_revoked"]):
            conn.execute("INSERT INTO app_user (user_id, role) VALUES (%s, 'caregiver')", (uid,))
        conn.execute(
            "INSERT INTO app_user (user_id, role, doctor_id) VALUES (%s, 'doctor', %s)",
            (w["doc_user"], w["doctor"]),
        )
        conn.execute(
            "INSERT INTO app_user (user_id, role) VALUES (%s, 'desk'), (%s, 'compliance')",
            (w["desk"], w["comp"]),
        )

        # The doctor treats patient A only.
        conn.execute(
            "INSERT INTO slot (slot_id, doctor_id, clinic_id, starts_at) VALUES (%s, %s, %s, %s)",
            (w["slot"], w["doctor"], w["clinic"], now + timedelta(days=1)),
        )
        conn.execute(
            "INSERT INTO appointment (appt_id, patient_id, slot_id, status, source, idempotency_key,"
            " created_by)"
            " VALUES (%s, %s, %s, 'booked', 'assistant', %s, %s)",
            (w["appt"], w["pa"], w["slot"], f"rls-{w['appt']}", w["ua"]),
        )

        # Caregiver consents on patient A: valid, expired, revoked.
        consent = (
            "INSERT INTO consent (patient_id, grantee_user_id, scope, purpose, granted_by, granted_at,"
            " expires_at, revoked_at) VALUES (%s, %s, %s, 'family care', %s, %s, %s, %s)"
        )
        conn.execute(
            consent,
            (
                w["pa"],
                w["carer_ok"],
                ["records:read", "appointments:read", "appointments:write"],
                w["ua"],
                now - timedelta(days=1),
                now + timedelta(days=30),
                None,
            ),
        )
        conn.execute(
            consent,
            (
                w["pa"],
                w["carer_expired"],
                ["records:read", "appointments:read"],
                w["ua"],
                now - timedelta(days=10),
                now - timedelta(days=1),
                None,
            ),
        )
        conn.execute(
            consent,
            (
                w["pa"],
                w["carer_revoked"],
                ["records:read", "appointments:read"],
                w["ua"],
                now - timedelta(days=1),
                now + timedelta(days=30),
                now,
            ),
        )

        for doc, pid, uid in ((w["doc_a"], w["pa"], w["ua"]), (w["doc_b"], w["pb"], w["ub"])):
            conn.execute(
                "INSERT INTO document (doc_id, patient_id, type, uri, sha256, uploaded_by)"
                " VALUES (%s, %s, 'lab_report', %s, %s, %s)",
                (doc, pid, f"s3://test/{doc}.pdf", doc, uid),
            )
            for ordinal in (0, 1):
                conn.execute(
                    "INSERT INTO doc_chunk (doc_id, patient_id, page, ordinal, text)"
                    " VALUES (%s, %s, 1, %s, %s)",
                    (doc, pid, ordinal, f"LDL 162 mg/dL chunk {ordinal} of {pid}"),
                )
    return w


def as_(user_id: str, role: str, patient_id: str | None = None) -> AuthContext:
    return {"user_id": user_id, "role": role, "acting_for_patient_id": patient_id}  # type: ignore[typeddict-item]


async def chunk_patients(pool, auth: AuthContext) -> set[str]:
    """Every patient whose chunks the caller can see, with NO application-level filter."""
    async with scoped(pool, auth) as conn:
        rows = await (await conn.execute("SELECT DISTINCT patient_id::text AS p FROM doc_chunk")).fetchall()
    return {r["p"] for r in rows}  # type: ignore[call-overload]


# ---- the bypass that would make all of this decorative ------------------------------------------


def test_app_role_cannot_bypass_rls():
    with psycopg.connect(get_settings().database_url) as conn:
        row = conn.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
    assert row == (False, False), "the app must not connect as a superuser or a BYPASSRLS role"


async def test_no_context_sees_nothing(pool, records_world):
    async with pool.connection() as conn:
        rows = await (await conn.execute("SELECT count(*) AS n FROM doc_chunk")).fetchone()
    assert rows["n"] == 0  # type: ignore[index]


# ---- the access matrix ------------------------------------------------------------------------


async def test_patient_sees_only_own_chunks_even_when_asking_for_another(pool, records_world):
    w = records_world
    patient_a = as_(w["ua"], "patient", w["pa"])
    assert await chunk_patients(pool, patient_a) == {w["pa"]}
    async with scoped(pool, patient_a) as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM doc_chunk WHERE patient_id = %s", (w["pb"],))
        assert (await cur.fetchone())["n"] == 0  # type: ignore[index]


@pytest.mark.parametrize(
    ("carer", "expected"), [("carer_ok", "pa"), ("carer_expired", None), ("carer_revoked", None)]
)
async def test_caregiver_needs_valid_unrevoked_consent(pool, records_world, carer, expected):
    w = records_world
    seen = await chunk_patients(pool, as_(w[carer], "caregiver"))
    assert seen == ({w[expected]} if expected else set())


async def test_doctor_sees_only_treated_patients(pool, records_world):
    w = records_world
    assert await chunk_patients(pool, as_(w["doc_user"], "doctor")) == {w["pa"]}


async def test_records_retrieval_is_rls_scoped(pool, records_world):
    w = records_world
    chunks = await retrieve(pool, as_(w["ua"], "patient", w["pa"]), question="LDL")

    assert chunks
    assert {chunk.patient_id for chunk in chunks} == {w["pa"]}


async def test_records_qa_requires_verified_citations_and_audits_reads(pool, records_world):
    w = records_world
    auth = as_(w["ua"], "patient", w["pa"])
    chat = EgressChatClient(
        FakeChatModel(structured={"answer": "Your LDL was 162 mg/dL.", "citation_ids": ["C1"]})
    )

    answer = await answer_question(pool, chat, auth, question="LDL")

    assert answer.status == "answered"
    assert len(answer.citations) == 1
    async with scoped(pool, auth) as conn:
        row = await (
            await conn.execute(
                "SELECT count(*) AS n FROM audit_event WHERE action = 'read' AND resource = 'document'"
            )
        ).fetchone()
    assert row["n"] == 1  # type: ignore[index]


async def test_records_qa_rejects_unretrieved_citations(pool, records_world):
    w = records_world
    chat = EgressChatClient(FakeChatModel(structured={"answer": "Looks fine.", "citation_ids": ["made-up"]}))

    answer = await answer_question(pool, chat, as_(w["ua"], "patient", w["pa"]), question="LDL")

    assert answer.status == "insufficient_evidence"
    assert answer.citations == []


@pytest.mark.parametrize("role", ["desk", "compliance"])
async def test_desk_and_compliance_see_no_clinical_chunks(pool, records_world, role):
    w = records_world
    user = w["desk"] if role == "desk" else w["comp"]
    assert await chunk_patients(pool, as_(user, role)) == set()


async def test_desk_sees_demographics_patient_sees_only_self(pool, records_world):
    w = records_world
    async with scoped(pool, as_(w["desk"], "desk")) as conn:
        desk_rows = await (await conn.execute("SELECT patient_id::text AS p FROM patient")).fetchall()
    async with scoped(pool, as_(w["ua"], "patient", w["pa"])) as conn:
        own_rows = await (await conn.execute("SELECT patient_id::text AS p FROM patient")).fetchall()
    assert {w["pa"], w["pb"]} <= {r["p"] for r in desk_rows}  # type: ignore[call-overload]
    assert {r["p"] for r in own_rows} == {w["pa"]}  # type: ignore[call-overload]


async def test_appointment_rls_uses_appointment_consent_not_record_consent(pool, records_world):
    w = records_world
    async with scoped(pool, as_(w["ua"], "patient", w["pa"])) as conn:
        patient_rows = await (await conn.execute("SELECT patient_id::text AS p FROM appointment")).fetchall()
    async with scoped(pool, as_(w["carer_ok"], "caregiver")) as conn:
        carer_rows = await (await conn.execute("SELECT patient_id::text AS p FROM appointment")).fetchall()
    async with scoped(pool, as_(w["carer_expired"], "caregiver")) as conn:
        expired_rows = await (await conn.execute("SELECT patient_id::text AS p FROM appointment")).fetchall()
    async with scoped(pool, as_(w["desk"], "desk")) as conn:
        desk_rows = await (await conn.execute("SELECT patient_id::text AS p FROM appointment")).fetchall()

    assert {r["p"] for r in patient_rows} == {w["pa"]}  # type: ignore[call-overload]
    assert {r["p"] for r in carer_rows} == {w["pa"]}  # type: ignore[call-overload]
    assert expired_rows == []
    assert {w["pa"]} <= {r["p"] for r in desk_rows}  # type: ignore[call-overload]


async def test_handoff_rls_limits_patient_reads_but_opens_desk_queue(pool, records_world):
    w = records_world
    with psycopg.connect(get_settings().migration_database_url) as conn, conn.transaction():
        conn.execute(
            "INSERT INTO handoff_ticket (kind, patient_id, reason, thread_id, created_by)"
            " VALUES ('front_desk', %s, 'needs_help', 't-rls', %s)",
            (w["pa"], w["ua"]),
        )
        conn.execute(
            "INSERT INTO handoff_ticket (kind, patient_id, reason, thread_id, created_by)"
            " VALUES ('front_desk', %s, 'needs_help', 't-hidden', %s)",
            (w["pb"], w["ub"]),
        )

    async with scoped(pool, as_(w["ua"], "patient", w["pa"])) as conn:
        own = await (await conn.execute("SELECT patient_id::text AS p FROM handoff_ticket")).fetchall()
    async with scoped(pool, as_(w["desk"], "desk")) as conn:
        desk = await (await conn.execute("SELECT patient_id::text AS p FROM handoff_ticket")).fetchall()

    assert {r["p"] for r in own} == {w["pa"]}  # type: ignore[call-overload]
    assert {w["pa"], w["pb"]} <= {r["p"] for r in desk}  # type: ignore[call-overload]


async def test_audit_reads_are_patient_scoped_unless_compliance(pool, records_world):
    w = records_world
    with psycopg.connect(get_settings().migration_database_url) as conn, conn.transaction():
        conn.execute(
            "INSERT INTO audit_event (actor_id, actor_role, action, resource, record_id, patient_id, purpose)"
            " VALUES (%s, 'patient', 'read', 'document', %s, %s, 'records qa')",
            (w["ua"], w["doc_a"], w["pa"]),
        )
        conn.execute(
            "INSERT INTO audit_event (actor_id, actor_role, action, resource, record_id, patient_id, purpose)"
            " VALUES (%s, 'patient', 'read', 'document', %s, %s, 'records qa')",
            (w["ub"], w["doc_b"], w["pb"]),
        )

    async with scoped(pool, as_(w["ua"], "patient", w["pa"])) as conn:
        own = await (await conn.execute("SELECT patient_id::text AS p FROM audit_event")).fetchall()
    async with scoped(pool, as_(w["comp"], "compliance")) as conn:
        compliance = await (await conn.execute("SELECT patient_id::text AS p FROM audit_event")).fetchall()

    assert {r["p"] for r in own} == {w["pa"]}  # type: ignore[call-overload]
    assert {w["pa"], w["pb"]} <= {r["p"] for r in compliance}  # type: ignore[call-overload]


# ---- writes ---------------------------------------------------------------------------------


async def test_only_the_system_worker_writes_chunks(pool, records_world):
    w = records_world
    insert = "INSERT INTO doc_chunk (doc_id, patient_id, page, ordinal, text) VALUES (%s, %s, 2, 0, 'x')"
    with pytest.raises(psycopg.errors.InsufficientPrivilege):  # new row violates row-level security policy
        async with scoped(pool, as_(w["ua"], "patient", w["pa"])) as conn:
            await conn.execute(insert, (w["doc_a"], w["pa"]))
    async with scoped_system(pool) as conn:
        await conn.execute(insert, (w["doc_a"], w["pa"]))


async def test_patient_can_revoke_but_not_extend_consent(pool, records_world):
    w = records_world
    patient_a = as_(w["ua"], "patient", w["pa"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with scoped(pool, patient_a) as conn:
            await conn.execute(
                "UPDATE consent SET expires_at = now() + interval '10 years' WHERE patient_id = %s",
                (w["pa"],),
            )
    async with scoped(pool, patient_a) as conn:
        cur = await conn.execute(
            "UPDATE consent SET revoked_at = now() WHERE grantee_user_id = %s AND revoked_at IS NULL",
            (w["carer_ok"],),
        )
        assert cur.rowcount == 1
    assert await chunk_patients(pool, as_(w["carer_ok"], "caregiver")) == set()  # revocation is immediate


async def test_patient_cannot_grant_consent_on_someone_elses_record(pool, records_world):
    w = records_world
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with scoped(pool, as_(w["ua"], "patient", w["pa"])) as conn:
            await conn.execute(
                "INSERT INTO consent (patient_id, grantee_user_id, scope, purpose, granted_by, expires_at)"
                " VALUES (%s, %s, '{records:read}', 'x', %s, now() + interval '1 day')",
                (w["pb"], w["carer_ok"], w["ua"]),
            )


async def test_consent_service_grants_lists_and_revokes(pool, records_world):
    w = records_world
    auth = as_(w["ua"], "patient", w["pa"])
    grantee = _uuid()
    with psycopg.connect(get_settings().migration_database_url) as conn, conn.transaction():
        conn.execute("INSERT INTO app_user (user_id, role) VALUES (%s, 'caregiver')", (grantee,))

    grant = await grant_consent(
        pool,
        auth,
        patient_id=w["pa"],
        grantee_user_id=grantee,
        scope=["records:read"],
        purpose="family care",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    listed = await list_consents(pool, auth)
    revoked = await revoke_consent(pool, auth, consent_id=grant.consent_id)

    assert grant.consent_id in {item.consent_id for item in listed}
    assert revoked.revoked_at is not None
    assert await chunk_patients(pool, as_(grantee, "caregiver")) == set()


# ---- context hygiene ------------------------------------------------------------------------


async def test_context_does_not_leak_across_pooled_connections(pool, records_world):
    w = records_world
    assert await chunk_patients(pool, as_(w["ua"], "patient", w["pa"])) == {w["pa"]}
    # Same pool, next checkout, no scoped(): SET LOCAL ended with the transaction.
    async with pool.connection() as conn:
        row = await (await conn.execute("SELECT current_setting('app.user_id', true) AS u")).fetchone()
        n = await (await conn.execute("SELECT count(*) AS n FROM doc_chunk")).fetchone()
    assert row["u"] in (None, "")  # type: ignore[index]
    assert n["n"] == 0  # type: ignore[index]


def test_signed_notes_are_immutable_even_for_the_owner(admin_url, records_world):
    w = records_world
    note_id, encounter_id = _uuid(), _uuid()
    with psycopg.connect(admin_url) as conn:
        conn.execute(
            "INSERT INTO encounter (encounter_id, appt_id, patient_id, doctor_id) VALUES (%s, %s, %s, %s)",
            (encounter_id, w["appt"], w["pa"], w["doctor"]),
        )
        conn.execute(
            "INSERT INTO note_version (note_id, version, encounter_id, patient_id, doctor_id, soap_json,"
            " draft_json, content_hash, signed_by) VALUES (%s, 1, %s, %s, %s, '{}', '{}', 'h', %s)",
            (note_id, encounter_id, w["pa"], w["doctor"], w["doc_user"]),
        )
        conn.commit()
        # A row-level trigger only fires on existing rows, so the note must exist first.
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            conn.execute(
                'UPDATE note_version SET soap_json = \'{"S": "edited"}\' WHERE note_id = %s', (note_id,)
            )
        conn.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            conn.execute("DELETE FROM note_version WHERE note_id = %s", (note_id,))
