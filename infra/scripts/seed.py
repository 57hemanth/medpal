"""Seed the local database: the generated network (6 hospitals, 22 clinics, 38 specialties, 500 doctors,
~480k slots) plus a few fixed development identities, so the README's curl examples keep working.

DESTRUCTIVE: resets reference, scheduling and identity data (TRUNCATE … CASCADE). Audit rows are kept.
Refuses to run when MEDPAL_ENV=prod. Runs as the owner role: seeding is an admin task.

    uv run --group data python -m infra.scripts.seed
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

from data.synthetic.generate import OUT_DIR, write_outputs
from services.platform.config import get_settings

# Load order follows foreign keys.
TABLES = [
    ("hospitals.csv", "hospital", "hospital_id, name, city"),
    ("clinics.csv", "clinic", "clinic_id, hospital_id, name, city, district, opens_at, closes_at"),
    ("specialties.csv", "specialty", "specialty_id, name"),
    ("doctors.csv", "doctor", "doctor_id, name, specialty_id, languages, years, synthetic"),
    ("doctor_clinic.csv", "doctor_clinic", "doctor_id, clinic_id"),
    ("slots.csv", "slot", "doctor_id, clinic_id, starts_at, capacity, synthetic"),
]
RESET = "TRUNCATE hospital, clinic, specialty, doctor, doctor_clinic, slot, patient, app_user CASCADE"

# Fixed development identities (stable ids so dev auth headers and docs keep working).
PRIYA_PATIENT, PRIYA_USER = "00000000-0000-0000-0000-0000000b0001", "00000000-0000-0000-0000-0000000e0001"
RAVI_PATIENT, RAVI_USER = "00000000-0000-0000-0000-0000000b0002", "00000000-0000-0000-0000-0000000e0002"
MOTHER_PATIENT, MOTHER_USER = "00000000-0000-0000-0000-0000000b0003", "00000000-0000-0000-0000-0000000e0005"
DESK_USER = "00000000-0000-0000-0000-0000000e0003"
DOCTOR_USER = "00000000-0000-0000-0000-0000000e0004"
COMPLIANCE_USER = "00000000-0000-0000-0000-0000000e0006"


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
        (PRIYA_PATIENT, "Priya S", "1992-04-11", "Pune", "en", baner[0] if baner else None),
        (RAVI_PATIENT, "Ravi K", "1985-09-02", "Hyderabad", "te", None),
        (MOTHER_PATIENT, "Sunita S", "1963-07-21", "Pune", "mr", None),  # Priya's mother: caregiver scenario
    ]
    for pid, name, dob, city, lang, clinic in patients:
        conn.execute(
            "INSERT INTO patient (patient_id, name, dob, city, language, preferred_clinic_id)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (pid, name, dob, city, lang, clinic),
        )
    for uid, pid in ((PRIYA_USER, PRIYA_PATIENT), (RAVI_USER, RAVI_PATIENT), (MOTHER_USER, MOTHER_PATIENT)):
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
    # Mother grants Priya read access to her records for 180 days.
    now = datetime.now(UTC)
    conn.execute(
        "INSERT INTO consent (patient_id, grantee_user_id, scope, purpose, granted_by, granted_at,"
        " expires_at)"
        " VALUES (%s, %s, '{records:read}', 'family care', %s, %s, %s)",
        (MOTHER_PATIENT, PRIYA_USER, MOTHER_USER, now, now + timedelta(days=180)),
    )


def main() -> None:
    settings = get_settings()
    if settings.env == "prod":
        sys.exit("refusing to seed: MEDPAL_ENV=prod")
    if not (OUT_DIR / "slots.csv").exists():
        print("generated layer missing: generating…")
        write_outputs()
    with psycopg.connect(settings.migration_database_url) as conn, conn.transaction():
        conn.execute(RESET)
        counts = {table: _copy(conn, OUT_DIR / file, table, cols) for file, table, cols in TABLES}
        _identities(conn)
    print("loaded:", ", ".join(f"{t}={n:,}" for t, n in counts.items()))
    print("dev identities: Priya (patient + caregiver for her mother), Ravi, desk, doctor, compliance")
    print(
        "try: curl -s localhost:8000/triage -H 'content-type: application/json' "
        f"-H 'X-Dev-User-Id: {PRIYA_USER}' -H 'X-Dev-Role: patient' -H 'X-Dev-Patient-Id: {PRIYA_PATIENT}' "
        """-d '{"text": "knee pain for a week"}'"""
    )


if __name__ == "__main__":
    main()
