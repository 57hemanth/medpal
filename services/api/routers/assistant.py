"""One assistant endpoint: the supervisor routes a message to triage, records and scribe in parallel.

Each specialist answers in exactly the shape of its own endpoint, with its own thread id, so the client
continues a paused specialist on that specialist's endpoint (e.g. POST /triage/{thread_id}/resume).
"""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel, Field

from services.agent.supervisor.graph import build_supervisor_graph
from services.agent.supervisor.planner import ModelPlanner
from services.api.deps import auth_ctx
from services.api.routers.scribe import _session_out
from services.api.routers.triage import _to_out
from services.api.tracing import traced
from services.platform import audit
from services.platform.auth import AuthContext
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
        self, auth: AuthContext, *, question: str, patient_id: str | None, encounter_id: str | None
    ) -> dict[str, Any]:
        if auth["role"] == "doctor":
            patient_id = await self._encounter_patient(auth, encounter_id)
            if patient_id is None:
                return {"status": "patient_required", "reply": "Open one of your consultations first."}
        result = await answer_question(
            self._state.app_pool, self._state.chat_client, auth, question=question, patient_id=patient_id
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
