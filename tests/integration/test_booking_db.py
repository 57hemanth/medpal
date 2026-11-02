"""Booking guarantees against real Postgres: idempotency, capacity under concurrency, audit."""

import asyncio
import uuid

import psycopg
import pytest

from services.platform.auth import AuthContext
from services.platform.config import get_settings
from services.scheduling import service as scheduling

pytestmark = pytest.mark.integration


def auth_for(world) -> AuthContext:
    return {"user_id": world["user"], "role": "patient", "acting_for_patient_id": world["patient"]}


async def test_full_slot_rejects_a_new_booking(pool, world):
    auth = auth_for(world)
    first = await scheduling.reserve(
        pool, auth, slot_id=world["slot"], patient_id=world["patient"], idempotency_key=f"k-{uuid.uuid4()}"
    )
    second = await scheduling.reserve(
        pool, auth, slot_id=world["slot"], patient_id=world["patient"], idempotency_key=f"k-{uuid.uuid4()}"
    )
    assert first is not None
    assert second is None  # capacity 1 already taken: graph will re-offer


async def test_same_key_twice_is_one_booking(pool, world, admin_url):
    auth = auth_for(world)
    key = f"k-{uuid.uuid4()}"
    a = await scheduling.reserve(
        pool, auth, slot_id=world["slot"], patient_id=world["patient"], idempotency_key=key
    )
    b = await scheduling.reserve(
        pool, auth, slot_id=world["slot"], patient_id=world["patient"], idempotency_key=key
    )
    assert a is not None and a == b
    with psycopg.connect(admin_url) as conn:
        n = conn.execute("SELECT count(*) FROM appointment WHERE slot_id = %s", (world["slot"],)).fetchone()
    assert n is not None and n[0] == 1


async def test_concurrent_bookings_never_exceed_capacity(pool, world):
    auth = auth_for(world)
    results = await asyncio.gather(
        *[
            scheduling.reserve(
                pool,
                auth,
                slot_id=world["slot"],
                patient_id=world["patient"],
                idempotency_key=f"k-{uuid.uuid4()}",
            )
            for _ in range(20)
        ]
    )
    assert sum(r is not None for r in results) == 1


async def test_booking_writes_audit_event(pool, world, admin_url):
    auth = auth_for(world)
    appt = await scheduling.reserve(
        pool, auth, slot_id=world["slot"], patient_id=world["patient"], idempotency_key=f"k-{uuid.uuid4()}"
    )
    with psycopg.connect(admin_url) as conn:
        row = conn.execute(
            "SELECT actor_id::text, action, purpose FROM audit_event"
            " WHERE resource = 'appointment' AND record_id = %s",
            (appt,),
        ).fetchone()
    assert row == (world["user"], "write", "booking")


def test_audit_event_is_append_only(world, admin_url):
    insert = (
        "INSERT INTO audit_event (actor_id, actor_role, action, resource, record_id, purpose)"
        " VALUES (%s, 'patient', 'read', 'test', 'x', 'test')"
    )
    # The app role may append and read, but has no UPDATE/DELETE grant at all.
    with psycopg.connect(get_settings().database_url) as conn:
        conn.execute(insert, (world["user"],))
        conn.commit()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE audit_event SET purpose = 'tampered' WHERE actor_id = %s", (world["user"],))
        conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM audit_event WHERE actor_id = %s", (world["user"],))
    # Even the owner is stopped by the trigger: tampering needs dropping the trigger, which is a DDL trail.
    with psycopg.connect(admin_url) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute("UPDATE audit_event SET purpose = 'tampered' WHERE actor_id = %s", (world["user"],))
        conn.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute("DELETE FROM audit_event WHERE actor_id = %s", (world["user"],))
