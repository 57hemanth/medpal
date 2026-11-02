"""Scheduling: shortlist free slots and reserve one. Deterministic code (automation ladder rung 1).

Booking contract (ADR-10):
  * one transaction: lock the slot row, count booked appointments, insert if under capacity;
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

Row = dict[str, Any]  # pools use psycopg's dict_row factory (services.platform.db)


async def _one(cur: AsyncCursor[Any]) -> Row | None:
    return cast(Row | None, await cur.fetchone())


async def _all(cur: AsyncCursor[Any]) -> list[Row]:
    return cast(list[Row], await cur.fetchall())


@dataclass(frozen=True)
class Candidate:
    doctor_id: str
    doctor_name: str
    slot_id: str
    clinic_name: str
    starts_at: datetime


# Earliest free slot per doctor for a specialty. The Redis display cache (plan T4.3) sits in
# front of this for listing only; reserve() always re-checks capacity under a row lock.
_SHORTLIST = """
SELECT DISTINCT ON (d.doctor_id)
       d.doctor_id::text, d.name AS doctor_name, s.slot_id::text, c.name AS clinic_name, s.starts_at
FROM slot s
JOIN doctor d    ON d.doctor_id = s.doctor_id
JOIN specialty p ON p.specialty_id = d.specialty_id
JOIN clinic c    ON c.clinic_id = s.clinic_id
WHERE p.name = %(specialty)s
  AND s.starts_at > now()
  AND s.capacity > (SELECT count(*) FROM appointment a WHERE a.slot_id = s.slot_id AND a.status = 'booked')
  AND NOT (s.slot_id = ANY(%(exclude)s::uuid[]))
ORDER BY d.doctor_id, s.starts_at
"""


async def shortlist(
    pool: AsyncConnectionPool, specialty: str, *, limit: int = 3, exclude_slot_ids: list[str] | None = None
) -> list[Candidate]:
    async with pool.connection() as conn:
        cur = await conn.execute(_SHORTLIST, {"specialty": specialty, "exclude": exclude_slot_ids or []})
        rows = await _all(cur)
    ranked = sorted(rows, key=lambda r: r["starts_at"])[:limit]
    return [Candidate(**r) for r in ranked]


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

        cur = await conn.execute("SELECT capacity FROM slot WHERE slot_id = %s FOR UPDATE", (slot_id,))
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
