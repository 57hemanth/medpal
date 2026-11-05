"""Triage and booking graph ("find my doctor").

    intake → red_flag_rules ─flag─► emergency_handoff ─► END
                 │ clear
                 ▼
          safety_screen  (interrupt: patient answers 7 yes/no red-flag questions) ─any yes─► emergency
                 │ all no
                 ▼
          match_specialty ─unclear─► ask_clarifying (interrupt: one question) → back to red_flag_rules
                 │                    (still unclear after one answer → front_desk_handoff)
                 ▼
          shortlist ─none─► front_desk_handoff ─► END
                               ▼
                       present_options  (interrupt: patient picks a slot)
                               ▼
                             book ─full─► shortlist (re-offer, slot excluded; ≤3 times)
                               ▼ ok
                            notify ─► END

Rule: side effects never sit in a node that calls interrupt(), because that node re-runs
from its start on resume (verified against langgraph 1.2.19).
"""

from collections.abc import Awaitable
from typing import Protocol

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from services.platform.auth import AuthContext

from .rules import RULESET_STATUS, RULESET_VERSION, SAFETY_SCREEN, match_red_flags, screen_red_flags
from .rules import match_specialty as classify_specialty
from .state import CandidateView, TriageState

MAX_REOFFERS = 3
MAX_CLARIFICATIONS = 1
CLARIFY_QUESTION = (
    "Could you tell me a bit more? Where is the problem, how long has it been going on, "
    "and what makes it better or worse?"
)

EMERGENCY_REPLY = (
    "These symptoms need urgent attention now. Please call 112 or go to the nearest emergency "
    "department. We have alerted MedPal's emergency desk and a nurse will call you shortly."
)
FRONT_DESK_REPLY = (
    "We couldn't find the right appointment automatically. Our front desk has your request "
    "and will contact you."
)


class TriageTools(Protocol):
    """Tools the graph may use. Implemented over Postgres in tools.py; faked in unit tests."""

    def shortlist(
        self, auth: AuthContext, specialty: str, exclude_slot_ids: list[str]
    ) -> Awaitable[list[CandidateView]]: ...

    def reserve(
        self, auth: AuthContext, *, slot_id: str, patient_id: str, idempotency_key: str, thread_id: str
    ) -> Awaitable[str | None]: ...

    def open_handoff(
        self, auth: AuthContext, *, kind: str, patient_id: str | None, reason: str, thread_id: str
    ) -> Awaitable[str]: ...


def _thread_id(config: RunnableConfig) -> str:
    return str(config["configurable"]["thread_id"])


def build_triage_graph(tools: TriageTools) -> StateGraph:
    async def intake(state: TriageState) -> TriageState:
        return {
            "intake_text": state["intake_text"].strip(),
            "red_flags": [],
            "ruleset_version": RULESET_VERSION,
            "ruleset_status": RULESET_STATUS,
            "excluded_slot_ids": [],
            "reoffer_count": 0,
        }

    async def red_flag_rules(state: TriageState) -> TriageState:
        return {"red_flags": match_red_flags(state["intake_text"])}

    async def safety_screen(state: TriageState) -> TriageState:
        # Pure: this node re-runs on resume, so no side effects here.
        questions = [{"key": q.key, "question": q.question} for q in SAFETY_SCREEN]
        answers = interrupt({"type": "safety_check", "questions": questions})
        flags = screen_red_flags(answers.get("safety_answers") if isinstance(answers, dict) else None)
        if flags is None:
            return {"safety_answers": None}  # incomplete or malformed: ask again
        return {"safety_answers": answers["safety_answers"], "red_flags": [f"{f}:screen" for f in flags]}

    async def emergency_handoff(state: TriageState, config: RunnableConfig) -> TriageState:
        auth = state["auth"]
        ticket = await tools.open_handoff(
            auth,
            kind="emergency",
            patient_id=auth["acting_for_patient_id"],
            reason=",".join(state["red_flags"]),
            thread_id=_thread_id(config),
        )
        return {"handoff_ticket_id": ticket, "outcome": "emergency", "reply": EMERGENCY_REPLY}

    async def match_specialty(state: TriageState) -> TriageState:
        match = classify_specialty(state["intake_text"])
        return {
            "specialty": match.specialty,
            "confidence": match.confidence,
            "specialty_rule_id": match.rule_id,
            "needs_clarification": match.needs_clarification,
        }

    async def ask_clarifying(state: TriageState) -> TriageState:
        # Pure: re-runs on resume. The answer is appended, then every check runs again on the new text,
        # including the red-flag rules: "and now my chest hurts" must still escalate.
        answer = interrupt({"type": "clarify", "question": CLARIFY_QUESTION})
        text = answer.get("answer") if isinstance(answer, dict) else None
        if not isinstance(text, str) or not text.strip():
            return {"clarified": False}
        return {
            "intake_text": f"{state['intake_text']}. {text.strip()[:2000]}",
            "clarify_count": state.get("clarify_count", 0) + 1,
            "clarified": True,
        }

    async def shortlist(state: TriageState) -> TriageState:
        specialty = state.get("specialty") or "General Medicine"
        candidates = await tools.shortlist(state["auth"], specialty, state.get("excluded_slot_ids", []))
        return {"candidates": candidates, "chosen_slot_id": None}

    async def present_options(state: TriageState) -> TriageState:
        # Pure: this node re-runs on resume, so no side effects here.
        choice = interrupt({"type": "pick_slot", "candidates": state["candidates"]})
        offered = {c["slot_id"] for c in state["candidates"]}
        slot_id = choice.get("slot_id") if isinstance(choice, dict) else None
        key = choice.get("idempotency_key") if isinstance(choice, dict) else None
        if slot_id not in offered or not key:
            # A slot we didn't offer (or no idempotency key) is not a valid choice: ask again.
            return {"chosen_slot_id": None, "idempotency_key": None}
        return {"chosen_slot_id": slot_id, "idempotency_key": key}

    async def book(state: TriageState, config: RunnableConfig) -> TriageState:
        auth = state["auth"]
        patient_id = auth["acting_for_patient_id"]
        slot_id, key = state.get("chosen_slot_id"), state.get("idempotency_key")
        # Real checks, not asserts: asserts vanish under `python -O`.
        if not patient_id:
            raise RuntimeError("API must resolve the acting patient before the run starts")
        if not slot_id or not key:
            raise RuntimeError("book reached without a validated slot choice")
        booking = await tools.reserve(
            auth, slot_id=slot_id, patient_id=patient_id, idempotency_key=key, thread_id=_thread_id(config)
        )
        if booking:
            return {"booking_id": booking}
        return {
            "booking_id": None,
            "excluded_slot_ids": [*state.get("excluded_slot_ids", []), slot_id],
            "reoffer_count": state.get("reoffer_count", 0) + 1,
        }

    async def notify(state: TriageState) -> TriageState:
        # SMS delivery is planned: a fixed template with no clinical content.
        chosen = next(c for c in state["candidates"] if c["slot_id"] == state["chosen_slot_id"])
        reply = f"Booked with {chosen['doctor_name']} at {chosen['clinic_name']} on {chosen['display_time']}."
        return {"outcome": "booked", "reply": reply}

    async def front_desk_handoff(state: TriageState, config: RunnableConfig) -> TriageState:
        auth = state["auth"]
        if state.get("needs_clarification"):
            reason = "unclear_symptoms"
        else:
            reason = "no_slots" if not state.get("candidates") else "too_many_reoffers"
        ticket = await tools.open_handoff(
            auth,
            kind="front_desk",
            patient_id=auth["acting_for_patient_id"],
            reason=reason,
            thread_id=_thread_id(config),
        )
        return {"handoff_ticket_id": ticket, "outcome": "front_desk", "reply": FRONT_DESK_REPLY}

    # ---- routing ----
    def after_rules(state: TriageState) -> str:
        if state["red_flags"]:
            return "emergency_handoff"
        # The safety screen is asked once per run; a clarification re-runs the rules but not the screen.
        return "match_specialty" if state.get("safety_answers") is not None else "safety_screen"

    def after_specialty(state: TriageState) -> str:
        if not state.get("needs_clarification"):
            return "shortlist"
        return (
            "ask_clarifying" if state.get("clarify_count", 0) < MAX_CLARIFICATIONS else "front_desk_handoff"
        )

    def after_clarify(state: TriageState) -> str:
        return "red_flag_rules" if state.get("clarified") else "ask_clarifying"

    def after_screen(state: TriageState) -> str:
        if state.get("safety_answers") is None:
            return "safety_screen"
        return "emergency_handoff" if state["red_flags"] else "match_specialty"

    def after_shortlist(state: TriageState) -> str:
        return "present_options" if state["candidates"] else "front_desk_handoff"

    def after_choice(state: TriageState) -> str:
        return "book" if state.get("chosen_slot_id") else "present_options"

    def after_book(state: TriageState) -> str:
        if state.get("booking_id"):
            return "notify"
        return "shortlist" if state.get("reoffer_count", 0) < MAX_REOFFERS else "front_desk_handoff"

    g = StateGraph(TriageState)
    g.add_node("intake", intake)
    g.add_node("red_flag_rules", red_flag_rules)
    g.add_node("safety_screen", safety_screen)
    g.add_node("emergency_handoff", emergency_handoff)
    g.add_node("match_specialty", match_specialty)
    g.add_node("ask_clarifying", ask_clarifying)
    g.add_node("shortlist", shortlist)
    g.add_node("present_options", present_options)
    g.add_node("book", book)
    g.add_node("notify", notify)
    g.add_node("front_desk_handoff", front_desk_handoff)

    g.add_edge(START, "intake")
    g.add_edge("intake", "red_flag_rules")
    g.add_conditional_edges(
        "red_flag_rules", after_rules, ["emergency_handoff", "safety_screen", "match_specialty"]
    )
    g.add_conditional_edges(
        "safety_screen", after_screen, ["safety_screen", "emergency_handoff", "match_specialty"]
    )
    g.add_conditional_edges(
        "match_specialty", after_specialty, ["shortlist", "ask_clarifying", "front_desk_handoff"]
    )
    g.add_conditional_edges("ask_clarifying", after_clarify, ["red_flag_rules", "ask_clarifying"])
    g.add_conditional_edges("shortlist", after_shortlist, ["present_options", "front_desk_handoff"])
    g.add_conditional_edges("present_options", after_choice, ["book", "present_options"])
    g.add_conditional_edges("book", after_book, ["notify", "shortlist", "front_desk_handoff"])
    for terminal in ("notify", "emergency_handoff", "front_desk_handoff"):
        g.add_edge(terminal, END)
    return g
