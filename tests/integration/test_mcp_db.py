"""MCP tools on real Postgres: same booking guarantees and audit as the REST API."""

import uuid

import psycopg
import pytest
from mcp.client.client import Client

from services.mcp_server.server import build_mcp_server
from services.platform.auth import AuthContext

pytestmark = pytest.mark.integration


async def test_agent_finds_and_books_a_slot_idempotently_with_audit(pool, world, admin_url):
    patient: AuthContext = {
        "user_id": world["user"],
        "role": "patient",
        "acting_for_patient_id": world["patient"],
    }
    server = build_mcp_server(lambda: pool, lambda _ctx: patient)
    key = f"mcp-{uuid.uuid4()}"
    async with Client(server) as client:
        found = await client.call_tool("find_appointment_slots", {"specialty": world["specialty_name"]})
        assert not found.is_error
        slots = found.structured_content["result"]
        assert [s["slot_id"] for s in slots] == [world["slot"]]
        first = await client.call_tool("book_appointment", {"slot_id": world["slot"], "idempotency_key": key})
        again = await client.call_tool("book_appointment", {"slot_id": world["slot"], "idempotency_key": key})
    assert first.structured_content["status"] == "booked"
    assert again.structured_content == first.structured_content  # retry-safe
    with psycopg.connect(admin_url) as conn:
        audits = conn.execute(
            "SELECT count(*) FROM audit_event WHERE resource = 'appointment' AND record_id = %s",
            (first.structured_content["appointment_id"],),
        ).fetchone()
    assert audits == (1,)
