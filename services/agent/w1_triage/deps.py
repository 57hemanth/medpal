"""Postgres-backed implementation of the W1 tools (W1Deps)."""

from psycopg_pool import AsyncConnectionPool

from services.platform.auth import AuthContext
from services.scheduling import service as scheduling

from .state import CandidateView


class PgW1Deps:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def shortlist(self, specialty: str, exclude_slot_ids: list[str]) -> list[CandidateView]:
        rows = await scheduling.shortlist(self._pool, specialty, exclude_slot_ids=exclude_slot_ids)
        return [
            CandidateView(
                doctor_id=c.doctor_id,
                doctor_name=c.doctor_name,
                slot_id=c.slot_id,
                clinic_name=c.clinic_name,
                starts_at=c.starts_at.isoformat(),
            )
            for c in rows
        ]

    async def reserve(
        self, auth: AuthContext, *, slot_id: str, patient_id: str, idempotency_key: str, thread_id: str
    ) -> str | None:
        return await scheduling.reserve(
            self._pool,
            auth,
            slot_id=slot_id,
            patient_id=patient_id,
            idempotency_key=idempotency_key,
            trace_id=thread_id,
        )

    async def open_handoff(
        self, auth: AuthContext, *, kind: str, patient_id: str | None, reason: str, thread_id: str
    ) -> str:
        return await scheduling.open_handoff(
            self._pool, auth, kind=kind, patient_id=patient_id, reason=reason, thread_id=thread_id
        )
