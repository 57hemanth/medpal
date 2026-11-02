import operator
from typing import Annotated, Literal, TypedDict

from services.platform.auth import AuthContext

Outcome = Literal["booked", "emergency", "front_desk"]


class CandidateView(TypedDict):
    doctor_id: str
    doctor_name: str
    slot_id: str
    clinic_name: str
    starts_at: str  # ISO 8601; state must stay JSON-serialisable for the checkpointer


class TriageState(TypedDict, total=False):
    # Injected by the API at run start; no node writes it.
    auth: AuthContext
    intake_text: str
    red_flags: list[str]
    specialty: str | None
    confidence: float | None
    candidates: list[CandidateView]
    excluded_slot_ids: list[str]  # slots that turned out full; never re-offered in this run
    reoffer_count: int
    chosen_slot_id: str | None
    idempotency_key: str | None
    booking_id: str | None
    handoff_ticket_id: str | None
    outcome: Outcome | None
    reply: str | None
    audit_ids: Annotated[list[str], operator.add]
