"""Postgres-backed implementation of the triage tools (TriageTools)."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from psycopg_pool import AsyncConnectionPool

from services.platform.auth import AuthContext
from services.scheduling import service as scheduling

from .state import CandidateView
from .times import PART_HOURS

# All MedPal clinics are in India; times are shown to patients in clinic local time.
CLINIC_TZ = ZoneInfo("Asia/Kolkata")


def display_time(local: datetime) -> str:
    """'Mon 9 Nov, 08:00': what a patient reads; no ambiguity about the zone or a UTC offset."""
    return f"{local:%a} {local.day} {local:%b}, {local:%H:%M}"


# "More times" for one doctor: up to TIMES_PER_DAY times on each of the next TIMES_DAYS days that have
# any, at least TIMES_GAP apart, so a patient sees a spread rather than twelve 15-minute neighbours.
TIMES_DAYS = 3
TIMES_PER_DAY = 6
TIMES_GAP = timedelta(minutes=30)
SEARCH_DAYS = 14


def window(day: date | None, part_of_day: str | None) -> scheduling.TimeWindow:
    """A day (clinic local) and/or part of the day; with no day, the next SEARCH_DAYS days."""
    start = datetime.combine(day, time(0), CLINIC_TZ) if day else None
    end = (start + timedelta(days=1)) if start else datetime.now(CLINIC_TZ) + timedelta(days=SEARCH_DAYS)
    hours = PART_HOURS.get(part_of_day or "")
    return scheduling.TimeWindow(
        start=start, end=end, hour_from=hours[0] if hours else None, hour_to=hours[1] if hours else None
    )


def spread(rows: list[scheduling.Candidate]) -> list[scheduling.Candidate]:
    picked: list[scheduling.Candidate] = []
    per_day: dict[date, list[datetime]] = {}
    for row in rows:
        local = row.starts_at.astimezone(CLINIC_TZ)
        times = per_day.get(local.date())
        if times is None:
            if len(per_day) == TIMES_DAYS:
                break
            times = per_day[local.date()] = []
        if len(times) < TIMES_PER_DAY and (not times or local - times[-1] >= TIMES_GAP):
            times.append(local)
            picked.append(row)
    return picked


def _view(c: scheduling.Candidate) -> CandidateView:
    local = c.starts_at.astimezone(CLINIC_TZ)
    return CandidateView(
        doctor_id=c.doctor_id,
        doctor_name=c.doctor_name,
        slot_id=c.slot_id,
        clinic_name=c.clinic_name,
        starts_at=local.isoformat(),
        display_time=display_time(local),
    )


class PgTriageTools:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def _prefs(self, auth: AuthContext) -> scheduling.PatientPreferences | None:
        patient_id = auth["acting_for_patient_id"]
        return await scheduling.patient_preferences(self._pool, auth, patient_id) if patient_id else None

    async def shortlist(
        self,
        auth: AuthContext,
        specialty: str,
        exclude_slot_ids: list[str],
        *,
        day: date | None = None,
        part_of_day: str | None = None,
    ) -> list[CandidateView]:
        rows = await scheduling.shortlist(
            self._pool,
            specialty,
            exclude_slot_ids=exclude_slot_ids,
            preferences=await self._prefs(auth),
            window=window(day, part_of_day) if day or part_of_day else None,
        )
        return [_view(c) for c in rows]

    async def doctor_times(
        self,
        auth: AuthContext,
        doctor_id: str,
        exclude_slot_ids: list[str],
        *,
        day: date | None = None,
        part_of_day: str | None = None,
    ) -> list[CandidateView]:
        rows = await scheduling.doctor_times(
            self._pool,
            doctor_id,
            exclude_slot_ids=exclude_slot_ids,
            preferences=await self._prefs(auth),
            window=window(day, part_of_day),
        )
        return [_view(c) for c in spread(rows)]

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
