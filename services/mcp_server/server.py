"""MCP tool server: scheduling and stock as tools any approved agent can call.

The tools are the same code paths as the REST API, so an agent gets exactly the guarantees a person
does: the caller's identity (verified OIDC token, or dev headers in dev only), row-level security,
idempotent booking under an advisory lock, and an audit row for every booking. No tool returns
another patient's data, and no tool takes a patient id: identity comes from the caller, never from
a tool argument a model could make up.

Served over streamable HTTP at /mcp by the API app, or standalone:

    uv run python -m services.mcp_server.server        # stdio, for a local agent
"""

from collections.abc import Callable
from typing import Any, cast

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from psycopg_pool import AsyncConnectionPool

from services.platform.auth import AuthContext
from services.platform.config import get_settings
from services.platform.identity import IdentityError, resolve_identity
from services.scheduling import service as scheduling
from services.scheduling.service import PatientPreferences

Resolver = Callable[[Context], AuthContext]
INSTRUCTIONS = (
    "MedPal scheduling and pharmacy-stock tools. Never use these for emergencies: anyone with chest pain, "
    "trouble breathing, fainting, stroke signs, heavy bleeding, poisoning or self-harm thoughts must be told "
    "to call 112 and be handed to a human. Booking requires the patient's explicit choice of slot."
)


def header_identity(ctx: Context) -> AuthContext:
    """Production resolver: identity from a verified bearer token (or dev headers in dev mode)."""
    try:
        return resolve_identity(ctx.headers, get_settings())
    except IdentityError as exc:
        raise ToolError(f"unauthenticated: {exc}") from exc


def build_mcp_server(
    pool: Callable[[], AsyncConnectionPool], resolve: Resolver = header_identity
) -> MCPServer:
    server = MCPServer(name="MedPal", instructions=INSTRUCTIONS)

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def find_appointment_slots(
        specialty: str, ctx: Context, city: str | None = None, language: str | None = None, limit: int = 3
    ) -> list[dict[str, Any]]:
        """Earliest free slot per doctor for a specialty, soonest first (no patient data)."""
        resolve(ctx)
        prefs = PatientPreferences(city=city, language=language)
        rows = await scheduling.shortlist(pool(), specialty, limit=max(1, min(limit, 10)), preferences=prefs)
        return [
            {
                "slot_id": r.slot_id,
                "doctor_name": r.doctor_name,
                "clinic_name": r.clinic_name,
                "starts_at": r.starts_at.isoformat(),
            }
            for r in rows
        ]

    @server.tool(annotations=ToolAnnotations(destructive_hint=False, idempotent_hint=True))
    async def book_appointment(slot_id: str, idempotency_key: str, ctx: Context) -> dict[str, Any]:
        """Book a slot for the calling patient. Retrying with the same key returns the same booking."""
        auth = resolve(ctx)
        if auth["role"] != "patient" or not auth["acting_for_patient_id"]:
            raise ToolError("only a patient can book for themselves")
        if not 8 <= len(idempotency_key) <= 128:
            raise ToolError("idempotency_key must be 8 to 128 characters")
        appt = await scheduling.reserve(
            pool(),
            auth,
            slot_id=slot_id,
            patient_id=auth["acting_for_patient_id"],
            idempotency_key=idempotency_key,
            source="assistant",
        )
        return {"status": "booked", "appointment_id": appt} if appt else {"status": "slot_full"}

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def check_medicine_stock(medicine: str, clinic: str, ctx: Context) -> dict[str, Any]:
        """Stock of one medicine at one clinic, with the time the count was taken. Never substitutes."""
        auth = resolve(ctx)
        if auth["role"] not in ("doctor", "pharmacist", "desk"):
            raise ToolError("stock is available to clinical and front-desk staff")
        async with pool().connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT m.name, ms.qty, ms.as_of FROM medicine m"
                    " JOIN medicine_stock ms ON ms.medicine_id = m.medicine_id"
                    " JOIN clinic c ON c.clinic_id = ms.clinic_id"
                    " WHERE lower(m.name) = lower(%s) AND lower(c.name) = lower(%s)",
                    (medicine, clinic),
                )
            ).fetchone()
        if row is None:
            return {"medicine": medicine, "clinic": clinic, "status": "not_in_formulary_or_unknown_clinic"}
        r = cast(dict[str, Any], row)
        return {
            "medicine": r["name"],
            "clinic": clinic,
            "status": "in_stock" if r["qty"] > 0 else "out_of_stock",
            "qty": r["qty"],
            "as_of": r["as_of"].isoformat(),
        }

    return server


if __name__ == "__main__":  # stdio transport for a local agent; dev identity comes from the environment
    import asyncio
    import os

    from services.platform.db import app_pool

    async def _main() -> None:
        settings = get_settings()
        db = app_pool(settings)
        await db.open()
        env_identity = resolve_identity(
            {
                k.replace("MEDPAL_MCP_", "x-dev-").replace("_", "-").lower(): v
                for k, v in os.environ.items()
                if k.startswith("MEDPAL_MCP_")
            },
            settings,
        )
        try:
            await build_mcp_server(lambda: db, lambda _ctx: env_identity).run_stdio_async()
        finally:
            await db.close()

    asyncio.run(_main())
