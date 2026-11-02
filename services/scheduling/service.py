"""Scheduling: shortlist free slots and reserve one. Deterministic code (automation ladder rung 1).

Booking contract (ADR-0005):
  * one transaction: advisory-lock the slot, count booked appointments, insert if under capacity;
  * a client-generated idempotency key makes retries return the same appointment;
  * a full slot returns None so the graph can re-offer, never double-book.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from psycopg import AsyncCursor
from psycopg_pool import AsyncConnectionPool

from services.platform import audit
from services.platform.auth import AuthContext
from services.platform.db import scoped

Row = dict[str, Any]  # pools use psycopg's dict_row factory (services.platform.db)


async def _one(cur: AsyncCursor[Any]) -> Row | None:
    return cast(Row | None, await cur.fetchone())


async def _all(cur: AsyncCursor[Any]) -> list[Row]:
    return cast(list[Row], await cur.fetchall())


@dataclass(frozen=True)
class PatientPreferences:
    city: str | None = None
    language: str | None = None
    preferred_clinic_id: str | None = None


async def patient_preferences(
    pool: AsyncConnectionPool, auth: AuthContext, patient_id: str
) -> PatientPreferences:
    """Read the acting patient's location and language, as the caller (RLS: only rows they may see)."""
    async with scoped(pool, auth) as conn:
        cur = await conn.execute(
            "SELECT city, language, preferred_clinic_id::text AS preferred_clinic_id FROM patient"
            " WHERE patient_id = %s",
            (patient_id,),
        )
        row = await _one(cur)
    return PatientPreferences(**row) if row else PatientPreferences()


@dataclass(frozen=True)
class Candidate:
    doctor_id: str
    doctor_name: str
    slot_id: str
    clinic_name: str
    starts_at: datetime


# Earliest free slot per doctor for a specialty, ranked:
#   same city as the patient (filter) → doctor speaks the patient's language → preferred clinic → soonest.
# Shape matters at 480k slots: the LATERAL ... LIMIT 1 lets each doctor's (doctor_id, starts_at) index scan
# stop at the first free slot, so cost grows with how booked-up doctors are, not with the calendar size.
# Measured with 6,200 bookings: 4.5 ms vs 60 ms for a DISTINCT ON over every future slot.
# A display cache may sit in front for listing only; reserve() always re-checks capacity.
_SHORTLIST = """
SELECT d.doctor_id::text, d.name AS doctor_name, f.slot_id::text, c.name AS clinic_name, f.starts_at
FROM doctor d
JOIN specialty p ON p.specialty_id = d.specialty_id AND p.name = %(specialty)s
CROSS JOIN LATERAL (
    SELECT s.slot_id, s.clinic_id, s.starts_at
    FROM slot s
    WHERE s.doctor_id = d.doctor_id
      AND s.starts_at > now()
      AND NOT (s.slot_id = ANY(%(exclude)s::uuid[]))
      AND (%(city)s::text IS NULL
           OR s.clinic_id IN (SELECT clinic_id FROM clinic WHERE city = %(city)s::text))
      AND s.capacity > (SELECT count(*) FROM appointment a
                        WHERE a.slot_id = s.slot_id AND a.status = 'booked')
    ORDER BY s.starts_at
    LIMIT 1
) f
JOIN clinic c ON c.clinic_id = f.clinic_id
ORDER BY COALESCE(%(language)s::text = ANY (d.languages), false) DESC,
         COALESCE(f.clinic_id = %(preferred)s::uuid, false) DESC,
         f.starts_at,
         d.doctor_id
LIMIT %(limit)s
"""


async def shortlist(
    pool: AsyncConnectionPool,
    specialty: str,
    *,
    limit: int = 3,
    exclude_slot_ids: list[str] | None = None,
    preferences: PatientPreferences | None = None,
) -> list[Candidate]:
    prefs = preferences or PatientPreferences()
    params = {
        "specialty": specialty,
        "exclude": exclude_slot_ids or [],
        "limit": limit,
        "city": prefs.city,
        "language": prefs.language,
        "preferred": prefs.preferred_clinic_id,
    }
    async with pool.connection() as conn:
        rows = await _all(await conn.execute(_SHORTLIST, params))
    return [Candidate(**r) for r in rows]


async def reserve(
    pool: AsyncConnectionPool,
    auth: AuthContext,
    *,
    slot_id: str,
    patient_id: str,
    idempotency_key: str,
    source: str = "assistant",
    trace_id: str | None = None,
) -> str | None:
    """Book `slot_id` for `patient_id`. Returns the appointment id, or None if the slot is full."""
    async with pool.connection() as conn, conn.transaction():
        cur = await conn.execute(
            "SELECT appt_id::text FROM appointment WHERE idempotency_key = %s", (idempotency_key,)
        )
        existing = await _one(cur)
        if existing:
            return str(existing["appt_id"])

        # Serialise bookings per slot with a transaction-scoped advisory lock. FOR UPDATE would need
        # UPDATE privilege on `slot`, which the app role deliberately lacks (it must not edit capacity).
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"slot:{slot_id}",))
        cur = await conn.execute("SELECT capacity FROM slot WHERE slot_id = %s", (slot_id,))
        slot = await _one(cur)
        if slot is None:
            return None
        cur = await conn.execute(
            "SELECT count(*) AS n FROM appointment WHERE slot_id = %s AND status = 'booked'", (slot_id,)
        )
        booked = await _one(cur)
        if booked is not None and booked["n"] >= slot["capacity"]:
            return None

        cur = await conn.execute(
            """INSERT INTO appointment (patient_id, slot_id, status, source, idempotency_key, created_by)
               VALUES (%s, %s, 'booked', %s, %s, %s) RETURNING appt_id::text""",
            (patient_id, slot_id, source, idempotency_key, auth["user_id"]),
        )
        appt = await _one(cur)
        assert appt is not None
        appt_id = str(appt["appt_id"])
        await audit.write(
            conn,
            auth,
            action="write",
            resource="appointment",
            record_id=appt_id,
            patient_id=patient_id,
            purpose="booking",
            trace_id=trace_id,
        )
        return appt_id


async def open_handoff(
    pool: AsyncConnectionPool,
    auth: AuthContext,
    *,
    kind: str,
    patient_id: str | None,
    reason: str,
    thread_id: str | None,
) -> str:
    """Put a human-in-the-loop item in the desk/emergency queue."""
    async with pool.connection() as conn, conn.transaction():
        cur = await conn.execute(
            """INSERT INTO handoff_ticket (kind, patient_id, reason, thread_id, created_by)
               VALUES (%s, %s, %s, %s, %s) RETURNING ticket_id::text""",
            (kind, patient_id, reason, thread_id, auth["user_id"]),
        )
        row = await _one(cur)
        assert row is not None
        ticket_id = str(row["ticket_id"])
        await audit.write(
            conn,
            auth,
            action="write",
            resource="handoff_ticket",
            record_id=ticket_id,
            patient_id=patient_id,
            purpose=f"handoff:{kind}",
        )
        return ticket_id
