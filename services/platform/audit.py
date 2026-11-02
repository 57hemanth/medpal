"""Append-only audit trail. Every record read or write gets one row: actor, role, action,
record, patient, purpose, trace id. The compliance officer's question "who saw this record?"
is one SELECT on this table. UPDATE/DELETE are blocked by a trigger (migration 0001)."""

from psycopg import AsyncConnection

from .auth import AuthContext

_INSERT = """
INSERT INTO audit_event (actor_id, actor_role, action, resource, record_id, patient_id, purpose, trace_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
RETURNING event_id
"""


async def write(
    conn: AsyncConnection,
    auth: AuthContext,
    *,
    action: str,
    resource: str,
    record_id: str,
    patient_id: str | None,
    purpose: str,
    trace_id: str | None = None,
) -> str:
    cur = await conn.execute(
        _INSERT,
        (auth["user_id"], auth["role"], action, resource, record_id, patient_id, purpose, trace_id),
    )
    row = await cur.fetchone()
    assert row is not None
    return str(row["event_id"])  # type: ignore[call-overload]
