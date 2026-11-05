"""MCP tool server through a real MCP client (in-memory transport, no database)."""

from mcp.client.client import Client

from services.mcp_server.server import build_mcp_server
from services.platform.auth import AuthContext

DESK: AuthContext = {"user_id": "u-desk", "role": "desk", "acting_for_patient_id": None}


def _no_pool():
    raise AssertionError("this test must not reach the database")


async def test_tools_are_listed_with_safety_hints():
    async with Client(build_mcp_server(_no_pool, lambda _ctx: DESK)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"find_appointment_slots", "book_appointment", "check_medicine_stock"}
    assert tools["find_appointment_slots"].annotations.read_only_hint is True
    assert tools["check_medicine_stock"].annotations.read_only_hint is True
    assert tools["book_appointment"].annotations.idempotent_hint is True
    # Identity never comes from an argument a model could invent.
    assert all("patient_id" not in (t.input_schema.get("properties") or {}) for t in tools.values())


async def test_only_a_patient_can_book_and_the_database_is_never_touched_otherwise():
    async with Client(build_mcp_server(_no_pool, lambda _ctx: DESK)) as client:
        result = await client.call_tool(
            "book_appointment", {"slot_id": "s", "idempotency_key": "key-12345678"}
        )
    assert result.is_error
    assert "only a patient" in str(result.content)


async def test_unauthenticated_calls_are_refused():
    from mcp.server.mcpserver.exceptions import ToolError

    def deny(_ctx):
        raise ToolError("unauthenticated: missing bearer token")

    async with Client(build_mcp_server(_no_pool, deny)) as client:
        result = await client.call_tool("find_appointment_slots", {"specialty": "Cardiology"})
    assert result.is_error and "unauthenticated" in str(result.content)
