"""Small, idempotent dev dataset for slice 0. Fixed UUIDs, so the dev auth headers are stable.

This is NOT the generated layer (plan T2.6: 500 doctors, ~480k slots). It is just enough for
the W1 path: 1 hospital, 1 clinic, 2 specialties, 3 doctors, 3 days of slots, 2 patients.

    uv run python -m infra.scripts.dev_seed
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import psycopg

from services.platform.config import get_settings

IST = ZoneInfo("Asia/Kolkata")

HOSPITAL = "00000000-0000-0000-0000-0000000f0001"
CLINIC = "00000000-0000-0000-0000-0000000c0001"
SPECIALTIES = {
    "General Medicine": "00000000-0000-0000-0000-0000000a0001",
    "Orthopaedics": "00000000-0000-0000-0000-0000000a0002",
}
DOCTORS = [
    ("00000000-0000-0000-0000-0000000d0001", "Dr. Asha Kulkarni", "General Medicine", ["en", "hi", "mr"]),
    ("00000000-0000-0000-0000-0000000d0002", "Dr. Vikram Rao", "General Medicine", ["en", "te"]),
    ("00000000-0000-0000-0000-0000000d0003", "Dr. Neha Joshi", "Orthopaedics", ["en", "hi"]),
]
PATIENTS = [
    # (patient_id, user_id, name, dob)
    ("00000000-0000-0000-0000-0000000b0001", "00000000-0000-0000-0000-0000000e0001", "Priya S", "1992-04-11"),
    ("00000000-0000-0000-0000-0000000b0002", "00000000-0000-0000-0000-0000000e0002", "Ravi K", "1985-09-02"),
]
DESK_USER = "00000000-0000-0000-0000-0000000e0003"


def slot_times(days: int = 3) -> list[datetime]:
    """30-minute slots, 10:00-13:00 IST, starting tomorrow. A calendar is arithmetic: no LLM."""
    start = date.today() + timedelta(days=1)
    out = []
    for d in range(days):
        day = start + timedelta(days=d)
        for minutes in range(0, 180, 30):
            out.append(datetime.combine(day, time(10, 0), IST) + timedelta(minutes=minutes))
    return out


def main() -> None:
    with psycopg.connect(get_settings().database_url) as conn, conn.transaction():
        conn.execute(
            "INSERT INTO hospital (hospital_id, name, city) VALUES (%s, 'MedPal Baner Hospital', 'Pune')"
            " ON CONFLICT DO NOTHING",
            (HOSPITAL,),
        )
        conn.execute(
            """INSERT INTO clinic (clinic_id, hospital_id, name, city, district, opens_at, closes_at)
               VALUES (%s, %s, 'Baner Clinic', 'Pune', 'Pune', '09:00', '18:00') ON CONFLICT DO NOTHING""",
            (CLINIC, HOSPITAL),
        )
        for name, sid in SPECIALTIES.items():
            conn.execute(
                "INSERT INTO specialty (specialty_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (sid, name),
            )
        for did, name, spec, langs in DOCTORS:
            conn.execute(
                """INSERT INTO doctor (doctor_id, name, specialty_id, languages, years)
                   VALUES (%s, %s, %s, %s, 10) ON CONFLICT DO NOTHING""",
                (did, name, SPECIALTIES[spec], langs),
            )
            conn.execute(
                "INSERT INTO doctor_clinic (doctor_id, clinic_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (did, CLINIC),
            )
            for starts_at in slot_times():
                conn.execute(
                    """INSERT INTO slot (doctor_id, clinic_id, starts_at) VALUES (%s, %s, %s)
                       ON CONFLICT (doctor_id, starts_at) DO NOTHING""",
                    (did, CLINIC, starts_at),
                )
        for pid, uid, name, dob in PATIENTS:
            conn.execute(
                "INSERT INTO patient (patient_id, name, dob) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (pid, name, dob),
            )
            conn.execute(
                "INSERT INTO app_user (user_id, role, patient_id) VALUES (%s, 'patient', %s)"
                " ON CONFLICT DO NOTHING",
                (uid, pid),
            )
        conn.execute(
            "INSERT INTO app_user (user_id, role) VALUES (%s, 'desk') ON CONFLICT DO NOTHING", (DESK_USER,)
        )

    priya_pid, priya_uid = PATIENTS[0][0], PATIENTS[0][1]
    print("Seeded. Try:")
    print(
        "  curl -s localhost:8000/triage -H 'content-type: application/json' "
        f"-H 'X-Dev-User-Id: {priya_uid}' -H 'X-Dev-Role: patient' -H 'X-Dev-Patient-Id: {priya_pid}' "
        """-d '{"text": "knee pain for a week"}'"""
    )


if __name__ == "__main__":
    main()
