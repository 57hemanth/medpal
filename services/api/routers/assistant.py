"""One assistant endpoint: the supervisor routes a message to triage, records and scribe in parallel.

Each specialist answers in exactly the shape of its own endpoint, with its own thread id, so the client
continues a paused specialist on that specialist's endpoint (e.g. POST /triage/{thread_id}/resume).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Request
from langgraph.types import Command
from pydantic import BaseModel, Field

from services.agent.supervisor.graph import build_supervisor_graph
from services.agent.supervisor.planner import ModelPlanner
from services.agent.supervisor.visit import SPECIALTY_ABOUT, VisitFacts, answer_visit, asked_for
from services.agent.triage.times import TimeRequest, parse_time_request
from services.agent.triage.tools import CLINIC_TZ
from services.api.deps import auth_ctx
from services.api.routers.scribe import _session_out
from services.api.routers.triage import _to_out
from services.api.tracing import traced
from services.platform import audit
from services.platform.auth import AuthContext
from services.platform.config import get_settings
from services.platform.db import scoped
from services.records.qa import answer_question

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
Auth = Annotated[AuthContext, Depends(auth_ctx)]
MAX_PARALLEL_SPECIALISTS = 3


class AssistantIn(BaseModel):
    message: str = Field(min_length=2, max_length=4000)
    patient_id: str | None = None  # caregivers: whose records
    encounter_id: str | None = None  # doctors: the open consultation
    transcript: str | None = Field(default=None, max_length=100_000)
    # The triage run earlier in this chat, so follow-ups ("which doctor?") are answered from it.
    conversation_thread_id: str | None = None


class AssistantOut(BaseModel):
    trace_id: str
    outcome: Literal["delegated", "emergency", "front_desk"]
    planned_by: Literal["safety", "model", "rules"] | None = None
    reply: str
    results: list[dict[str, Any]]


class AppSpecialists:
    """The real specialists, reached through the same services and graphs as their own endpoints."""

    def __init__(self, app: FastAPI) -> None:
        self._state = app.state

    def new_id(self) -> str:
        return str(uuid.uuid4())

    async def audit(
        self,
        auth: AuthContext,
        *,
        specialist: str,
        delegation_id: str,
        trace_id: str,
        patient_id: str | None,
    ) -> None:
        async with scoped(self._state.app_pool, auth) as conn:
            await audit.write(
                conn,
                auth,
                action="delegate",
                resource=f"assistant.{specialist}",
                record_id=delegation_id,
                patient_id=patient_id,
                purpose="assistant routing",
                trace_id=trace_id,
            )

    async def triage(self, auth: AuthContext, *, text: str, thread_id: str) -> dict[str, Any]:
        out = await self._state.triage_graph.ainvoke(
            {"auth": auth, "intake_text": text}, {"configurable": {"thread_id": thread_id}}
        )
        return _to_out(thread_id, out).model_dump()

    async def records(
        self,
        auth: AuthContext,
        *,
        question: str,
        patient_id: str | None,
        encounter_id: str | None,
        trace_id: str,
    ) -> dict[str, Any]:
        if auth["role"] == "doctor":
            patient_id = await self._encounter_patient(auth, encounter_id)
            if patient_id is None:
                return {"status": "patient_required", "reply": "Open one of your consultations first."}
        result = await answer_question(
            self._state.app_pool,
            self._state.chat_client,
            auth,
            question=question,
            patient_id=patient_id,
            trace_id=trace_id,
            tier=get_settings().records_model_tier,
        )
        return {
            "status": result.status,
            "reply": result.answer,
            "citations": [
                {"chunk_id": c.chunk_id, "doc_id": c.doc_id, "page": c.page, "text": c.text}
                for c in result.citations
            ],
        }

    async def scribe(
        self, auth: AuthContext, *, encounter_id: str, transcript: str, thread_id: str
    ) -> dict[str, Any]:
        out = await self._state.scribe_graph.ainvoke(
            {"auth": auth, "encounter_id": encounter_id, "transcript": transcript},
            {"configurable": {"thread_id": thread_id}},
        )
        session = _session_out(thread_id, out).model_dump()
        return {**session, "reply": "A draft note is ready for your review."}

    async def visit(self, auth: AuthContext, *, thread_id: str, question: str) -> dict[str, Any]:
        """Facts about this chat's appointment, read from the triage run's saved state and stated by
        code (services/agent/supervisor/visit.py). No model writes the reply; only the caller's own run
        is readable."""
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await self._state.triage_graph.aget_state(config)
        values = snapshot.values or {}
        if values.get("auth", {}).get("user_id") != auth["user_id"]:
            return {"status": "not_found", "reply": "I can't find an appointment in this conversation."}
        request = parse_time_request(
            question, values.get("doctors_offered") or [], datetime.now(CLINIC_TZ).date()
        )
        if request and "present_options" in (snapshot.next or ()):
            if request.doctor_id is None and not (request.day or request.part_of_day):
                doctors = {c["doctor_id"]: c["doctor_name"] for c in values.get("candidates") or []}
                if len(doctors) > 1:
                    example = next(iter(doctors.values()))
                    return {
                        "status": "options",
                        "reply": "Which doctor would you like other times for? Tap “More times” under "
                        f"their name, or say “more times with {example}”. You can also ask for a day, "
                        "like “tomorrow evening”.",
                        "thread_id": thread_id,
                    }
                request = TimeRequest(doctor_id=next(iter(doctors), None), day=None, part_of_day=None)
            # The patient is still choosing: continue that same run with the new times.
            out = await self._state.triage_graph.ainvoke(
                Command(resume={"more_times": request.as_resume()}), config
            )
            return _to_out(thread_id, out).model_dump()
        if request and values.get("booking_id"):
            return {
                "status": "booked",
                "reply": "This appointment is already booked. To change the time, cancel it under "
                "Appointments and ask me again; I'll find you a new time.",
                "thread_id": thread_id,
            }
        specialty = values.get("specialty")
        candidates = values.get("candidates") or []
        chosen = next((c for c in candidates if c["slot_id"] == values.get("chosen_slot_id")), None)
        if values.get("booking_id") and chosen:
            facts = VisitFacts(
                doctor=chosen["doctor_name"],
                specialty=specialty,
                clinic=chosen["clinic_name"],
                time=chosen["display_time"],
                reference=str(values["booking_id"])[:8].upper(),
            )
            return {"status": "booked", "reply": answer_visit(question, facts), "thread_id": thread_id}
        if candidates:
            names = ", ".join(c["doctor_name"] for c in candidates)
            reply = (
                f"I found {len(candidates)} {specialty or ''} options: {names}. Choose one above to book it."
            )
            about = SPECIALTY_ABOUT.get(specialty or "")
            if about and "specialty" in asked_for(question):
                reply = f"They are {specialty} specialists: {about}. " + reply
            return {"status": "options", "reply": " ".join(reply.split()), "thread_id": thread_id}
        if values.get("outcome") == "emergency":
            return {"status": "emergency", "reply": "This conversation was passed to the emergency desk."}
        return {"status": "not_found", "reply": "Nothing has been booked in this conversation yet."}

    async def _encounter_patient(self, auth: AuthContext, encounter_id: str | None) -> str | None:
        if not encounter_id:
            return None
        async with scoped(self._state.app_pool, auth) as conn:
            cur = await conn.execute(
                "SELECT e.patient_id::text FROM encounter e JOIN app_user u ON u.doctor_id = e.doctor_id"
                " WHERE e.encounter_id = %s AND u.user_id = %s",
                (encounter_id, auth["user_id"]),
            )
            row = await cur.fetchone()
        return row[0] if row else None


def build_assistant(app: FastAPI) -> Any:
    planner = ModelPlanner(app.state.chat_client)
    return build_supervisor_graph(AppSpecialists(app), planner).compile()


@router.post("", response_model=AssistantOut)
async def ask(body: AssistantIn, request: Request, auth: Auth) -> AssistantOut:
    trace_id = str(uuid.uuid4())
    async with traced(request, "assistant", trace_id) as callbacks:
        out = await request.app.state.supervisor_graph.ainvoke(
            {
                "auth": auth,
                "trace_id": trace_id,
                "message": body.message,
                "patient_id": body.patient_id,
                "encounter_id": body.encounter_id,
                "transcript": body.transcript,
                "conversation_thread_id": body.conversation_thread_id,
                "results": [],
            },
            {"callbacks": callbacks, "max_concurrency": MAX_PARALLEL_SPECIALISTS},
        )
    results = sorted(out.get("results", []), key=lambda r: r["order"])
    return AssistantOut(
        trace_id=trace_id,
        outcome=out["outcome"],
        planned_by=out.get("planned_by"),
        reply=out["reply"],
        results=[{k: v for k, v in r.items() if k != "order"} for r in results],
    )
