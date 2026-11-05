"""Appointment and front-desk operations outside the triage graph."""

from typing import Any, cast

from psycopg_pool import AsyncConnectionPool

from services.platform import audit
from services.platform.auth import AuthContext
from services.platform.db import scoped


async def list_appointments(
    pool: AsyncConnectionPool,
    auth: AuthContext,
    *,
    when: str = "all",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Appointments the caller may see (row-level security decides which), newest first or soonest first.

    when: "upcoming" (booked, from now, soonest first), "past" (before now, newest first) or "all".
    """
    async with scoped(pool, auth) as conn:
        rows = await (
            await conn.execute(
                "SELECT a.appt_id::text, a.patient_id::text, p.name AS patient_name, a.status, a.source,"
                " s.starts_at, d.name AS doctor_name, sp.name AS specialty, c.name AS clinic_name, c.city"
                " FROM appointment a JOIN slot s ON s.slot_id = a.slot_id"
                " JOIN doctor d ON d.doctor_id = s.doctor_id"
                " JOIN specialty sp ON sp.specialty_id = d.specialty_id"
                " JOIN clinic c ON c.clinic_id = s.clinic_id"
                " LEFT JOIN patient p ON p.patient_id = a.patient_id"  # the name only where RLS allows
                " WHERE %(when)s = 'all'"
                " OR (%(when)s = 'upcoming' AND a.status = 'booked' AND s.starts_at >= now())"
                " OR (%(when)s = 'past' AND s.starts_at < now())"
                " ORDER BY CASE WHEN %(when)s = 'upcoming' THEN s.starts_at END ASC, s.starts_at DESC"
                " LIMIT %(limit)s",
                {"when": when, "limit": max(1, min(limit, 500))},
            )
        ).fetchall()
    return cast(list[dict[str, Any]], rows)


async def cancel_appointment(pool: AsyncConnectionPool, auth: AuthContext, *, appt_id: str) -> dict[str, Any]:
    async with scoped(pool, auth) as conn:
        row = await (
            await conn.execute(
                "UPDATE appointment SET status = 'cancelled' WHERE appt_id = %s AND status = 'booked'"
                " RETURNING appt_id::text, patient_id::text, status",
                (appt_id,),
            )
        ).fetchone()
        if row is None:
            raise PermissionError("appointment is not visible or cannot be cancelled")
        result = cast(dict[str, Any], row)
        await audit.write(
            conn,
            auth,
            action="cancel",
            resource="appointment",
            record_id=appt_id,
            patient_id=str(result["patient_id"]),
            purpose="appointment cancellation",
        )
    return result


async def list_handoffs(pool: AsyncConnectionPool, auth: AuthContext) -> list[dict[str, Any]]:
    async with scoped(pool, auth) as conn:
        rows = await (
            await conn.execute(
                "SELECT t.ticket_id::text, t.kind, t.status, t.patient_id::text, p.name AS patient_name,"
                " t.reason, t.thread_id, t.created_at"
                " FROM handoff_ticket t LEFT JOIN patient p ON p.patient_id = t.patient_id"
                " ORDER BY (t.status = 'closed'), (t.kind = 'emergency') DESC, t.created_at DESC LIMIT 300"
            )
        ).fetchall()
    return cast(list[dict[str, Any]], rows)


async def update_handoff_status(
    pool: AsyncConnectionPool, auth: AuthContext, *, ticket_id: str, status: str
) -> dict[str, Any]:
    async with scoped(pool, auth) as conn:
        row = await (
            await conn.execute(
                "UPDATE handoff_ticket SET status = %s WHERE ticket_id = %s"
                " RETURNING ticket_id::text, patient_id::text, kind, status",
                (status, ticket_id),
            )
        ).fetchone()
        if row is None:
            raise PermissionError("handoff is not visible or cannot be updated")
        result = cast(dict[str, Any], row)
        await audit.write(
            conn,
            auth,
            action="update",
            resource="handoff_ticket",
            record_id=ticket_id,
            patient_id=result["patient_id"],
            purpose="front desk queue",
        )
    return result
