"""Consultation encounters: a doctor starts one for their own appointment, then drafts and signs a note."""

from typing import Any, cast

from psycopg_pool import AsyncConnectionPool

from services.platform import audit
from services.platform.auth import AuthContext
from services.platform.db import scoped


async def start_encounter(pool: AsyncConnectionPool, auth: AuthContext, *, appt_id: str) -> str:
    """Return the encounter for this appointment, creating it once. Only the appointment's doctor may."""
    if auth["role"] != "doctor":
        raise PermissionError("only doctors start consultations")
    async with scoped(pool, auth) as conn:
        appt = await (
            await conn.execute(
                "SELECT a.appt_id::text, a.patient_id::text, s.doctor_id::text FROM appointment a"
                " JOIN slot s ON s.slot_id = a.slot_id WHERE a.appt_id = %s"
                " AND s.doctor_id = (SELECT u.doctor_id FROM app_user u WHERE u.user_id = app_user_id())"
                " AND a.status IN ('booked', 'attended')",
                (appt_id,),
            )
        ).fetchone()
        if appt is None:
            raise PermissionError("appointment is not yours or not active")
        row = cast(dict[str, Any], appt)
        created = await (
            await conn.execute(
                "INSERT INTO encounter (appt_id, patient_id, doctor_id) VALUES (%s, %s, %s)"
                " ON CONFLICT (appt_id) DO NOTHING RETURNING encounter_id::text",
                (appt_id, row["patient_id"], row["doctor_id"]),
            )
        ).fetchone()
        if created is None:
            existing = await (
                await conn.execute("SELECT encounter_id::text FROM encounter WHERE appt_id = %s", (appt_id,))
            ).fetchone()
            return str(cast(dict[str, Any], existing)["encounter_id"])
        encounter_id = str(cast(dict[str, Any], created)["encounter_id"])
        await audit.write(
            conn,
            auth,
            action="write",
            resource="encounter",
            record_id=encounter_id,
            patient_id=row["patient_id"],
            purpose="consultation",
        )
        return encounter_id


async def list_consultations(pool: AsyncConnectionPool, auth: AuthContext) -> list[dict[str, Any]]:
    """The doctor's own appointments, with the encounter and signed-note state of each."""
    if auth["role"] != "doctor":
        raise PermissionError("only doctors list consultations")
    async with scoped(pool, auth) as conn:
        rows = await (
            await conn.execute(
                "SELECT a.appt_id::text, s.starts_at, c.name AS clinic_name, p.name AS patient_name,"
                " e.encounter_id::text,"
                " EXISTS (SELECT 1 FROM note_version n WHERE n.encounter_id = e.encounter_id) AS signed"
                " FROM appointment a JOIN slot s ON s.slot_id = a.slot_id"
                " JOIN clinic c ON c.clinic_id = s.clinic_id"
                " LEFT JOIN patient p ON p.patient_id = a.patient_id"
                " LEFT JOIN encounter e ON e.appt_id = a.appt_id"
                " WHERE s.doctor_id = (SELECT u.doctor_id FROM app_user u WHERE u.user_id = app_user_id())"
                " AND a.status IN ('booked', 'attended')"
                " ORDER BY s.starts_at"
            )
        ).fetchall()
    return cast(list[dict[str, Any]], rows)
