"""Postgres-backed implementation of the triage tools (TriageTools)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from psycopg_pool import AsyncConnectionPool

from services.platform.auth import AuthContext
from services.scheduling import service as scheduling

from .state import CandidateView

# All MedPal clinics are in India; times are shown to patients in clinic local time.
CLINIC_TZ = ZoneInfo("Asia/Kolkata")


def display_time(local: datetime) -> str:
    """'Mon 9 Nov, 08:00': what a patient reads; no ambiguity about the zone or a UTC offset."""
    return f"{local:%a} {local.day} {local:%b}, {local:%H:%M}"


class PgTriageTools:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def shortlist(
        self, auth: AuthContext, specialty: str, exclude_slot_ids: list[str]
    ) -> list[CandidateView]:
        patient_id = auth["acting_for_patient_id"]
        prefs = await scheduling.patient_preferences(self._pool, auth, patient_id) if patient_id else None
        rows = await scheduling.shortlist(
            self._pool, specialty, exclude_slot_ids=exclude_slot_ids, preferences=prefs
        )
        views = []
        for c in rows:
            local = c.starts_at.astimezone(CLINIC_TZ)
            views.append(
                CandidateView(
                    doctor_id=c.doctor_id,
                    doctor_name=c.doctor_name,
                    slot_id=c.slot_id,
                    clinic_name=c.clinic_name,
                    starts_at=local.isoformat(),
                    display_time=display_time(local),
                )
            )
        return views

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
