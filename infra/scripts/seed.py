"""Seed the local database: the generated network (6 hospitals, 22 clinics, 38 specialties, 500 doctors,
~480k slots) plus a few fixed development identities, so the README's curl examples keep working.

DESTRUCTIVE: resets reference, scheduling and identity data (TRUNCATE … CASCADE). Audit rows are kept.
Refuses to run when MEDPAL_ENV=prod. Runs as the owner role: seeding is an admin task.

    uv run --group data python -m infra.scripts.seed
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

from data.synthetic.generate import OUT_DIR, write_outputs
from infra.scripts.sample_records import ASHA_ANNUAL_CHECK, LATA_BLOOD_AND_KIDNEY, load_sample_records
from services.pharmacy.classes import class_for
from services.platform.config import get_settings

# Load order follows foreign keys.
TABLES = [
    ("hospitals.csv", "hospital", "hospital_id, name, city"),
    ("clinics.csv", "clinic", "clinic_id, hospital_id, name, city, district, opens_at, closes_at"),
    ("specialties.csv", "specialty", "specialty_id, name"),
    ("doctors.csv", "doctor", "doctor_id, name, specialty_id, languages, years, synthetic"),
    ("doctor_clinic.csv", "doctor_clinic", "doctor_id, clinic_id"),
    ("slots.csv", "slot", "doctor_id, clinic_id, starts_at, capacity, synthetic"),
    ("medicines.csv", "medicine", "medicine_id, name, composition, pack_size, price_inr, source"),
    ("medicine_stock.csv", "medicine_stock", "clinic_id, medicine_id, qty, as_of"),
]
RESET = (
    "TRUNCATE hospital, clinic, specialty, doctor, doctor_clinic, slot, patient, app_user,"
    " medicine, medicine_stock CASCADE"
)

# Fixed development identities (stable ids so dev auth headers and docs keep working).
ASHA_PATIENT, ASHA_USER = "00000000-0000-0000-0000-0000000b0001", "00000000-0000-0000-0000-0000000e0001"
ROHAN_PATIENT, ROHAN_USER = "00000000-0000-0000-0000-0000000b0002", "00000000-0000-0000-0000-0000000e0002"
MOTHER_PATIENT, MOTHER_USER = "00000000-0000-0000-0000-0000000b0003", "00000000-0000-0000-0000-0000000e0005"
DESK_USER = "00000000-0000-0000-0000-0000000e0003"
DOCTOR_USER = "00000000-0000-0000-0000-0000000e0004"
COMPLIANCE_USER = "00000000-0000-0000-0000-0000000e0006"
PHARMACIST_USER = "00000000-0000-0000-0000-0000000e0007"


def _copy(conn: psycopg.Connection, path: Path, table: str, columns: str) -> int:
    with conn.cursor() as cur:
        with (
            cur.copy(f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv, HEADER true)") as copy,
            path.open("rb") as f,
        ):
            while chunk := f.read(1 << 20):
                copy.write(chunk)
        n = cur.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608 (table from constant list)
    return int(n[0]) if n else 0


def _identities(conn: psycopg.Connection) -> None:
    baner = conn.execute("SELECT clinic_id FROM clinic WHERE name = 'Baner Clinic'").fetchone()
    patients = [
        # (id, name, dob, city, language, preferred clinic)
        (ASHA_PATIENT, "Asha Verma", "1992-04-11", "Pune", "en", baner[0] if baner else None),
        (ROHAN_PATIENT, "Rohan Reddy", "1985-09-02", "Hyderabad", "te", None),
        (MOTHER_PATIENT, "Lata Verma", "1963-07-21", "Pune", "mr", None),  # Asha's mother: the caregiver case
    ]
    for pid, name, dob, city, lang, clinic in patients:
        conn.execute(
            "INSERT INTO patient (patient_id, name, dob, city, language, preferred_clinic_id)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (pid, name, dob, city, lang, clinic),
        )
    for uid, pid in ((ASHA_USER, ASHA_PATIENT), (ROHAN_USER, ROHAN_PATIENT), (MOTHER_USER, MOTHER_PATIENT)):
        conn.execute(
            "INSERT INTO app_user (user_id, role, patient_id) VALUES (%s, 'patient', %s)", (uid, pid)
        )
    conn.execute(
        "INSERT INTO app_user (user_id, role) VALUES (%s, 'desk'), (%s, 'compliance')",
        (DESK_USER, COMPLIANCE_USER),
    )
    # Link the doctor login to the first General Medicine doctor (deterministic from the seed).
    doctor = conn.execute(
        "SELECT d.doctor_id FROM doctor d JOIN specialty s USING (specialty_id)"
        " WHERE s.name = 'General Medicine' ORDER BY d.doctor_id LIMIT 1"
    ).fetchone()
    if doctor is None:
        raise RuntimeError("no General Medicine doctor in the generated layer")
    conn.execute(
        "INSERT INTO app_user (user_id, role, doctor_id) VALUES (%s, 'doctor', %s)", (DOCTOR_USER, doctor[0])
    )
    # The doctor's clinic for the demo: where their earliest open slot is. The pharmacist works there too,
    # so a note signed in the demo reserves its medicines where the pharmacist can see them.
    clinic = conn.execute(
        "SELECT clinic_id FROM slot WHERE doctor_id = %s AND starts_at > now() ORDER BY starts_at LIMIT 1",
        (doctor[0],),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO app_user (user_id, role, clinic_id) VALUES (%s, 'pharmacist', %s)",
        (PHARMACIST_USER, clinic),
    )
    # Three desk-booked consultations with that doctor, so the scribe can be tried more than once.
    for position, patient in enumerate((ROHAN_PATIENT, ASHA_PATIENT, MOTHER_PATIENT)):
        conn.execute(
            "INSERT INTO appointment (patient_id, slot_id, status, source, idempotency_key, created_by)"
            " SELECT %s, slot_id, 'booked', 'desk', %s, %s FROM slot"
            " WHERE doctor_id = %s AND clinic_id = %s AND starts_at > now()"
            " ORDER BY starts_at OFFSET %s LIMIT 1",
            (patient, f"seed-scribe-demo-{position}", DESK_USER, doctor[0], clinic, position),
        )
    _past_consultations(conn, doctor[0], clinic)
    # Lata grants her daughter Asha read access to her records for 180 days.
    now = datetime.now(UTC)
    conn.execute(
        "INSERT INTO consent (patient_id, grantee_user_id, scope, purpose, granted_by, granted_at,"
        " expires_at)"
        " VALUES (%s, %s, '{records:read}', 'family care', %s, %s, %s)",
        (MOTHER_PATIENT, ASHA_USER, MOTHER_USER, now, now + timedelta(days=180)),
    )


PAST_CONSULTATIONS = [
    # (patient, days ago, transcript, SOAP, medicines, dispensed already)
    (
        ROHAN_PATIENT,
        6,
        "Doctor: Fever for three days with body ache and a runny nose? Patient: Yes, and a mild cough. "
        "Doctor: Temperature 100.8 F, throat slightly red, chest clear. Take paracetamol 500 mg three times "
        "a day for three days and cetirizine 10 mg at night for five days. Plenty of fluids.",
        {
            "subjective": "Fever, body ache and runny nose for three days; mild cough.",
            "objective": "Temperature 100.8 F. Throat slightly red. Chest clear.",
            "assessment": "Viral upper respiratory infection.",
            "plan": "Paracetamol 500 mg three times a day for three days. Cetirizine 10 mg at night for five "
            "days. Fluids and rest. Review if fever lasts beyond five days.",
        },
        ["Paracetamol", "Cetirizine"],
        True,
    ),
    (
        ASHA_PATIENT,
        2,
        "Doctor: Burning in the stomach after meals for two weeks? Patient: Yes, and sometimes nausea. "
        "Doctor: Pantoprazole 40 mg every morning before breakfast for two weeks, and ondansetron 4 mg if "
        "nauseous. Cut down on tea and late dinners.",
        {
            "subjective": "Burning epigastric pain after meals for two weeks; occasional nausea.",
            "objective": "Abdomen soft, mild epigastric tenderness.",
            "assessment": "Acid peptic symptoms.",
            "plan": "Pantoprazole 40 mg before breakfast for two weeks. Ondansetron 4 mg if nauseous. "
            "Less tea, earlier dinners. Follow up in two weeks.",
        },
        ["Pantoprazole", "Ondansetron"],
        False,
    ),
    (
        MOTHER_PATIENT,
        1,
        "Doctor: Your blood pressure today is 152 over 94, and it was high last time too. Patient: I get "
        "headaches some evenings. Doctor: Start amlodipine 5 mg once daily. Less salt, a daily walk, and "
        "check BP at home. Review in four weeks.",
        {
            "subjective": "Occasional evening headaches.",
            "objective": "BP 152/94, raised on two visits.",
            "assessment": "Hypertension.",
            "plan": "Amlodipine 5 mg once daily. Low-salt diet, daily walk, home BP log. "
            "Review in four weeks.",
        },
        ["Amlodipine"],
        False,
    ),
]


def _past_consultations(conn: psycopg.Connection, doctor_id: object, clinic_id: object) -> None:
    """Signed consultations from the last week, so notes, prescriptions and the pharmacy queue have history.

    Written with the owner role (the seed is not a user). Prescriptions go through the same trigger as a
    real signature, so each is reserved at the clinic if stock allows.
    """
    import json
    import uuid

    from services.scribe.service import content_hash

    for patient, days_ago, transcript, soap, medicines, dispensed in PAST_CONSULTATIONS:
        soap = {**soap, "medicines": medicines}
        slot_id, appt_id, encounter_id, note_id = (str(uuid.uuid4()) for _ in range(4))
        when = datetime.now(UTC).replace(hour=5, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
        conn.execute(
            "INSERT INTO slot (slot_id, doctor_id, clinic_id, starts_at, capacity, synthetic)"
            " VALUES (%s, %s, %s, %s, 1, true)",
            (slot_id, doctor_id, clinic_id, when),
        )
        conn.execute(
            "INSERT INTO appointment (appt_id, patient_id, slot_id, status, source, idempotency_key,"
            " created_by) VALUES (%s, %s, %s, 'attended', 'desk', %s, %s)",
            (appt_id, patient, slot_id, f"seed-past-{appt_id}", DESK_USER),
        )
        conn.execute(
            "INSERT INTO encounter (encounter_id, appt_id, patient_id, doctor_id, started_at, transcript)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (encounter_id, appt_id, patient, doctor_id, when, transcript),
        )
        conn.execute(
            "INSERT INTO note_version (note_id, version, encounter_id, patient_id, doctor_id, soap_json,"
            " draft_json, edit_history, content_hash, signed_by, signed_at)"
            " VALUES (%s, 1, %s, %s, %s, %s, %s, '[]', %s, %s, %s)",
            (
                note_id,
                encounter_id,
                patient,
                doctor_id,
                json.dumps(soap),
                json.dumps(soap),
                content_hash(soap),
                DOCTOR_USER,
                when + timedelta(minutes=15),
            ),
        )
        for medicine in medicines:
            conn.execute(
                "INSERT INTO prescription (note_id, note_version, patient_id, medicine_id, medicine_text,"
                " dose, substitute_ok, set_by)"
                " SELECT %s, 1, %s, medicine_id, %s, 'as written in the signed note', false, %s"
                " FROM medicine WHERE name = %s",
                (note_id, patient, medicine, DOCTOR_USER, medicine),
            )
        if dispensed:
            conn.execute(
                "UPDATE medicine_reservation SET status = 'dispensed', closed_at = %s, closed_by = %s"
                " WHERE rx_id IN (SELECT rx_id FROM prescription WHERE note_id = %s)",
                (when + timedelta(hours=1), PHARMACIST_USER, note_id),
            )


def main() -> None:
    settings = get_settings()
    if settings.env == "prod":
        sys.exit("refusing to seed: MEDPAL_ENV=prod")
    if not all((OUT_DIR / name).exists() for name, _, _ in TABLES):
        print("generated layer missing: generating…")
        write_outputs()
    with psycopg.connect(settings.migration_database_url) as conn, conn.transaction():
        conn.execute(RESET)
        counts = {table: _copy(conn, OUT_DIR / file, table, cols) for file, table, cols in TABLES}
        # Stock arrives as a nightly feed: stamp it as this morning's, so freshness flags are meaningful.
        conn.execute("UPDATE medicine_stock SET as_of = date_trunc('day', now()) + interval '6 hours'")
        for name, composition in conn.execute("SELECT name, composition FROM medicine").fetchall():
            conn.execute(
                "UPDATE medicine SET therapeutic_class = %s WHERE name = %s",
                (class_for(name) or class_for(composition), name),
            )
        _identities(conn)
    # Sample reports go through the real upload path (validation, privacy scan, storage, indexing).
    reports = asyncio.run(
        load_sample_records(
            settings,
            [
                (ASHA_USER, ASHA_PATIENT, ASHA_ANNUAL_CHECK),
                (MOTHER_USER, MOTHER_PATIENT, LATA_BLOOD_AND_KIDNEY),
            ],
        )
    )
    print("loaded:", ", ".join(f"{t}={n:,}" for t, n in counts.items()), f"sample reports={reports}")
    print("dev identities: Asha (patient + caregiver for her mother Lata), Rohan, desk, doctor, compliance")
    print(
        "the doctor has three consultations (Rohan, Asha, Lata) ready for the scribe, and three signed ones"
    )
    print("the pharmacist works at the doctor's clinic; past prescriptions are reserved or dispensed there")
    print("sample reports: Asha's annual health check (3 pages), Lata's blood count and kidney function")
    print(
        "try: curl -s localhost:8000/triage -H 'content-type: application/json' "
        f"-H 'X-Dev-User-Id: {ASHA_USER}' -H 'X-Dev-Role: patient' -H 'X-Dev-Patient-Id: {ASHA_PATIENT}' "
        """-d '{"text": "knee pain for a week"}'"""
    )


if __name__ == "__main__":
    main()
