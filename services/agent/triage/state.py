import operator
from typing import Annotated, Any, Literal, TypedDict

from services.platform.auth import AuthContext

Outcome = Literal["booked", "emergency", "front_desk"]


class CandidateView(TypedDict):
    doctor_id: str
    doctor_name: str
    slot_id: str
    clinic_name: str
    starts_at: str  # ISO 8601 in clinic local time (IST); state must stay JSON-serialisable
    display_time: str  # what the patient reads, e.g. "Mon 9 Nov, 08:00"


class TriageState(TypedDict, total=False):
    # Injected by the API at run start; no node writes it.
    auth: AuthContext
    intake_text: str
    red_flags: list[str]
    safety_answers: dict[str, bool] | None
    clarify_count: int
    clarified: bool
    ruleset_version: str
    ruleset_status: str
    specialty: str | None
    # The model's second choice: shown to the patient, never booked automatically.
    alternative_specialty: str | None
    # The model's specialty guess from model_check, used only when the specialty rules are unsure.
    model_guess: dict[str, Any] | None
    # "timeout" or "unavailable" when the model added nothing on this pass.
    model_skipped: str | None
    confidence: float | None
    specialty_rule_id: str | None
    needs_clarification: bool
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
