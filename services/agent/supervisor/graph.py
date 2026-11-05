"""Supervisor: one message in, the right specialist graphs run in parallel, one combined reply out.

    screen ──(emergency)──────────────────────────────┐
       │                                              ▼
       └─► plan (model, else rules) ─► Send × N ─► delegate ─► combine ─► END
                     │ nothing to do                    (triage │ records │ scribe, in parallel)
                     └──────────────────────────────► front_desk ─► END

* **Safety before routing.** Red-flag rules run on the whole message before any model sees it. A patient
  emergency goes to triage alone, which opens the emergency ticket; nothing else runs.
* **The model only labels clauses.** The message is split into numbered clauses and the model may only
  say which specialist each number belongs to. Specialist requests are always the patient's own words,
  so a model can't rewrite a request, inject instructions or name another patient. Without a model,
  or if it fails, keyword rules route instead.
* **Role decides what may run**, not the model: patients get triage and records, caregivers get records
  for a patient they name, doctors get records and the scribe for their own consultation.
* **Specialists keep their own threads.** Each runs as its own durable thread (its pauses, ownership
  checks and audit stay intact) and the reply carries its thread id so the client continues there.
  Every delegation writes an audit row linking the specialist thread to the supervisor's trace.
"""

import operator
import re
from typing import Annotated, Any, Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from services.agent.triage.rules import match_red_flags, match_specialty
from services.agent.triage.times import asks_other_times
from services.platform.auth import AuthContext

Specialist = Literal["triage", "records", "scribe", "visit"]
SPECIALISTS: tuple[Specialist, ...] = ("triage", "records", "scribe", "visit")
ALLOWED: dict[str, frozenset[str]] = {
    "patient": frozenset({"triage", "records", "visit"}),
    "caregiver": frozenset({"records"}),
    "doctor": frozenset({"records", "scribe"}),
}
MAX_CLAUSES = 12
MAX_MESSAGE = 4000


class Task(TypedDict):
    specialist: Specialist
    request: str
    order: int  # position of the first clause, so replies come back in the order they were asked


class Delegation(TypedDict):
    """What one parallel branch receives (the Send payload)."""

    auth: AuthContext
    trace_id: str
    task: Task
    patient_id: str | None
    encounter_id: str | None
    transcript: str | None
    conversation_thread_id: str | None


class Planner(Protocol):
    async def assign(self, clauses: list[str], allowed: frozenset[str]) -> list[tuple[int, str]]:
        """(clause index, specialist or "none") pairs. May raise; the supervisor then uses rules."""
        ...


class Specialists(Protocol):
    def new_id(self) -> str: ...

    async def audit(
        self,
        auth: AuthContext,
        *,
        specialist: str,
        delegation_id: str,
        trace_id: str,
        patient_id: str | None,
    ) -> None: ...

    async def triage(self, auth: AuthContext, *, text: str, thread_id: str) -> dict[str, Any]: ...

    async def records(
        self,
        auth: AuthContext,
        *,
        question: str,
        patient_id: str | None,
        encounter_id: str | None,
        trace_id: str,
    ) -> dict[str, Any]: ...

    async def scribe(
        self, auth: AuthContext, *, encounter_id: str, transcript: str, thread_id: str
    ) -> dict[str, Any]: ...

    async def visit(self, auth: AuthContext, *, thread_id: str, question: str) -> dict[str, Any]:
        """Answer about the appointment found or booked earlier in this conversation, from saved state."""
        ...


class SupervisorState(TypedDict, total=False):
    auth: AuthContext
    trace_id: str
    message: str
    patient_id: str | None  # a caregiver names whose records they mean
    encounter_id: str | None  # a doctor's open consultation
    transcript: str | None
    conversation_thread_id: str | None  # the triage run earlier in this chat, for follow-up questions
    clauses: list[str]
    tasks: list[Task]
    planned_by: Literal["safety", "model", "rules"]
    results: Annotated[list[dict[str, Any]], operator.add]
    reply: str
    outcome: Literal["delegated", "emergency", "front_desk"]


# ---- planning ------------------------------------------------------------------------------------

_SPLIT = re.compile(
    r"(?<=[.?!;])\s+|\n+|\s+(?:and also|also|plus)\s+"
    r"|,?\s+and\s+(?=(?:what|can|could|when|how|is|are|do|does|did|please|show|tell)\b)"
    # Hinglish: "…khane ke baad, aur mera vitamin D kitna tha?" ("and my vitamin D…")
    r"|,\s*aur\s+|\s+aur\s+(?=(?:mera|meri|mere|kya|kitna|kitni|kab|batao)\b)",
    re.I,
)
_RECORDS = re.compile(
    r"\b(?:report|reports|result|results|lab|labs|test|tests|ldl|hdl|hba1c|cholesterol|lipid|"
    r"glucose|sugar level|thyroid|tsh|vitamin|haemoglobin|hemoglobin|cbc|blood count|creatinine|"
    r"x-?ray|scan|mri|ultrasound|record|records|uploaded|what (?:was|were|is|are) (?:my|the|her|his))\b",
    re.I,
)
# Follow-ups about the appointment found or booked earlier in this chat ("which doctor?", "what time?").
_VISIT = re.compile(
    r"\b(?:doctor|doctor's|specialist|speciali[sz]ation|specialty|speciality|appointment|booking|booked|"
    r"visit|slot|clinic|hospital|address|where|when|what time|reference|confirmation|daktar)\b",
    re.I,
)
# ...unless the clause also describes a symptom: then it is a new triage, not a follow-up.
_SYMPTOM_ONLY = re.compile(
    r"\b(?:pain|ache|fever|cough|rash|itch|swelling|vomit|dizzy|headache|bleeding|breath|dard|bukhar)\b",
    re.I,
)
_SCRIBE = re.compile(
    r"\b(?:draft|note|notes|soap|scribe|write up|document (?:the|this) (?:visit|consult))", re.I
)
_SYMPTOM = re.compile(
    r"\b(?:pain|ache|aching|hurts?|fever|cough|cold|rash|itch|itchy|swelling|swollen|vomit|vomiting|"
    r"nausea|dizzy|dizziness|headache|tired|weak|weakness|bleeding|breath|sore|burning|injury|"
    r"appointment|see a doctor|book|dard|bukhar|khansi)\b",
    re.I,
)


def split_clauses(message: str) -> list[str]:
    parts = [p.strip(" ,") for p in _SPLIT.split(message[:MAX_MESSAGE]) if p and p.strip(" ,")]
    if len(parts) > MAX_CLAUSES:  # keep the tail together rather than dropping words
        parts = [*parts[: MAX_CLAUSES - 1], " ".join(parts[MAX_CLAUSES - 1 :])]
    return parts or [message.strip()]


def is_time_followup(clause: str) -> bool:
    """ "Other times for Chetan?", "anything tomorrow evening?": a follow-up to the options in this chat,
    never a new triage (which would ask the safety questions again). A symptom makes it a new triage."""
    return asks_other_times(clause) and not _SYMPTOM_ONLY.search(clause)


def rule_assign(
    clauses: list[str], role: str, *, has_transcript: bool, has_conversation: bool = False
) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for i, clause in enumerate(clauses):
        if (
            has_conversation
            and role == "patient"
            and (_VISIT.search(clause) or is_time_followup(clause))
            and not _SYMPTOM_ONLY.search(clause)
        ):
            out.append((i, "visit"))
        elif _RECORDS.search(clause):
            out.append((i, "records"))
        elif role == "doctor" and _SCRIBE.search(clause):
            out.append((i, "scribe"))
        elif role in ("patient", "caregiver") and (
            _SYMPTOM.search(clause)
            or match_red_flags(clause)
            or not match_specialty(clause).needs_clarification
        ):
            out.append((i, "triage"))
    if role == "doctor" and has_transcript and not any(s == "scribe" for _, s in out):
        out.append((len(clauses), "scribe"))  # an attached transcript is itself the request to draft
    return out


def build_tasks(
    clauses: list[str],
    assignments: list[tuple[int, str]],
    *,
    role: str,
    has_encounter: bool,
    has_transcript: bool,
    has_conversation: bool = False,
) -> list[Task]:
    """Validate the assignment against the role, then merge clauses per specialist (one run each)."""
    allowed = ALLOWED.get(role, frozenset())
    merged: dict[str, list[int]] = {}
    for index, specialist in assignments:
        # Only real clause numbers; the one extra slot past the end means "the attached transcript".
        limit = len(clauses) if specialist == "scribe" else len(clauses) - 1
        if specialist not in allowed or not (0 <= index <= limit):
            continue
        if specialist == "scribe" and not (has_encounter and has_transcript):
            continue
        if specialist == "visit" and not has_conversation:
            continue  # nothing booked or offered in this chat to talk about
        if specialist == "records" and role == "doctor" and not has_encounter:
            continue  # a doctor asks about the patient in front of them, never "any patient"
        merged.setdefault(specialist, [])
        if index not in merged[specialist]:
            merged[specialist].append(index)
    tasks: list[Task] = []
    for specialist, indices in merged.items():
        words = " ".join(clauses[i] for i in sorted(indices) if i < len(clauses))
        tasks.append(
            Task(specialist=specialist, request=words or "draft the note", order=min(indices))  # type: ignore[typeddict-item]
        )
    return sorted(tasks, key=lambda t: t["order"])


# ---- graph ---------------------------------------------------------------------------------------

_FAILED_REPLY = {
    "triage": "I couldn't finish finding you a doctor. The front desk can help you book.",
    "records": "I couldn't answer from your records just now. Please try again shortly.",
    "scribe": "The note draft isn't available right now; you can write the note by hand.",
    "visit": "I couldn't look up that appointment just now. It's listed under Appointments.",
}
_FRONT_DESK = {
    "patient": (
        "I couldn't tell what you need. Describe your symptoms to find a doctor, or ask about a report."
    ),
    "caregiver": "Ask about the reports of the person you care for, naming them on the request.",
    "doctor": "Open a consultation to draft a note, or ask about that patient's reports.",
}


def build_supervisor_graph(specialists: Specialists, planner: Planner | None = None) -> StateGraph:
    async def screen(state: SupervisorState) -> SupervisorState:
        message = state["message"]
        clauses = split_clauses(message)
        if state["auth"]["role"] == "patient" and match_red_flags(message):
            # Emergency first, alone: triage opens the emergency ticket. No model has seen the text.
            task = Task(specialist="triage", request=message, order=0)
            return {"clauses": clauses, "tasks": [task], "planned_by": "safety"}
        return {"clauses": clauses, "tasks": []}

    async def plan(state: SupervisorState) -> SupervisorState:
        role = state["auth"]["role"]
        clauses = state["clauses"]
        has_transcript = bool((state.get("transcript") or "").strip())
        has_conversation = bool(state.get("conversation_thread_id"))
        allowed = ALLOWED.get(role, frozenset())
        if not has_conversation:
            allowed = allowed - {"visit"}
        planned_by: Literal["model", "rules"] = "rules"
        assignments: list[tuple[int, str]] = []
        if planner is not None:
            try:
                assignments = [(i, s) for i, s in await planner.assign(clauses, allowed) if s != "none"]
                planned_by = "model" if assignments else "rules"
            except Exception:  # noqa: BLE001  any planner failure falls back to rules, never fails the run
                assignments = []
        if not assignments:
            assignments = rule_assign(
                clauses, role, has_transcript=has_transcript, has_conversation=has_conversation
            )
        if role == "patient" and has_conversation:
            # In a chat that already has a booking under way, a new triage (safety questions again)
            # needs a new symptom. Asking for other times, or anything without a symptom ("timings for
            # seema", "which doctor is cheapest?"), stays with the booking, whatever the planner said.
            followups = {
                i
                for i, clause in enumerate(clauses)
                if is_time_followup(clause)
                or (
                    (i, "triage") in assignments
                    and not _SYMPTOM_ONLY.search(clause)
                    and match_specialty(clause).needs_clarification
                )
            }
            assignments = [(i, s) for i, s in assignments if i not in followups]
            assignments += [(i, "visit") for i in sorted(followups)]
        if role == "doctor" and has_transcript and not any(s == "scribe" for _, s in assignments):
            assignments.append((len(clauses), "scribe"))
        if role == "patient" and not assignments:
            assignments = [(i, "triage") for i in range(len(clauses))]  # triage asks if it's unclear
        tasks = build_tasks(
            clauses,
            assignments,
            role=role,
            has_encounter=bool(state.get("encounter_id")),
            has_transcript=has_transcript,
            has_conversation=has_conversation,
        )
        return {"tasks": tasks, "planned_by": planned_by}

    def dispatch(state: SupervisorState) -> list[Send] | str:
        if not state.get("tasks"):
            return "front_desk"
        return [
            Send(
                "delegate",
                Delegation(
                    auth=state["auth"],
                    trace_id=state["trace_id"],
                    task=task,
                    patient_id=state.get("patient_id"),
                    encounter_id=state.get("encounter_id"),
                    transcript=state.get("transcript"),
                    conversation_thread_id=state.get("conversation_thread_id"),
                ),
            )
            for task in state["tasks"]
        ]

    async def delegate(state: Delegation) -> SupervisorState:
        task, auth = state["task"], state["auth"]
        # The delegation id is the specialist's own thread id, recorded against the supervisor's trace
        # before anything runs: "who asked, which specialist acted, under which trace" is one audit query.
        delegation_id = specialists.new_id()
        await specialists.audit(
            auth,
            specialist=task["specialist"],
            delegation_id=delegation_id,
            trace_id=state["trace_id"],
            patient_id=auth["acting_for_patient_id"] if auth["role"] == "patient" else state["patient_id"],
        )
        try:
            if task["specialist"] == "triage":
                result = await specialists.triage(auth, text=task["request"], thread_id=delegation_id)
            elif task["specialist"] == "visit":
                result = await specialists.visit(
                    auth, thread_id=state["conversation_thread_id"] or "", question=task["request"]
                )
            elif task["specialist"] == "records":
                result = await specialists.records(
                    auth,
                    question=task["request"],
                    patient_id=state["patient_id"],
                    encounter_id=state["encounter_id"],
                    trace_id=state["trace_id"],
                )
            else:
                result = await specialists.scribe(
                    auth,
                    encounter_id=state["encounter_id"] or "",
                    transcript=state["transcript"] or "",
                    thread_id=delegation_id,
                )
        except Exception as exc:  # noqa: BLE001  one failing specialist never sinks the others
            result = {
                "status": "failed",
                "reply": _FAILED_REPLY[task["specialist"]],
                "error_type": type(exc).__name__,
            }
        return {
            "results": [
                {
                    "delegation_id": delegation_id,
                    **result,
                    "specialist": task["specialist"],
                    "order": task["order"],
                }
            ]
        }

    async def combine(state: SupervisorState) -> SupervisorState:
        results = sorted(state.get("results", []), key=lambda r: r["order"])
        emergency = any(r.get("status") == "emergency" for r in results)
        return {
            "results": [],  # reducer: nothing added; ordering is applied to the reply only
            "reply": "\n\n".join(str(r.get("reply") or "") for r in results if r.get("reply")),
            "outcome": "emergency" if emergency else "delegated",
        }

    async def front_desk(state: SupervisorState) -> SupervisorState:
        role = state["auth"]["role"]
        reply = _FRONT_DESK.get(role, "This assistant is for patients, caregivers and doctors.")
        return {"reply": reply, "outcome": "front_desk"}

    g = StateGraph(SupervisorState)
    g.add_node("screen", screen)
    g.add_node("plan", plan)
    g.add_node("delegate", delegate, input_schema=Delegation)
    g.add_node("combine", combine)
    g.add_node("front_desk", front_desk)
    g.add_edge(START, "screen")
    g.add_conditional_edges(
        "screen",
        lambda state: dispatch(state) if state.get("planned_by") == "safety" else "plan",
        ["plan", "delegate", "front_desk"],
    )
    g.add_conditional_edges("plan", dispatch, ["delegate", "front_desk"])
    g.add_edge("delegate", "combine")
    g.add_edge("combine", END)
    g.add_edge("front_desk", END)
    return g
