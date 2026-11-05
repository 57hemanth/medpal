"""Records question answering with verified citations."""

import logging
import re
from dataclasses import dataclass

from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from services.platform import audit
from services.platform.auth import AuthContext
from services.platform.db import scoped
from services.platform.egress.client import EgressChatClient, ModelRequest, ModelUnavailable
from services.platform.phi.scrubber import BlockedIdentifier, EgressBlocked

from .retrieval import RetrievedChunk, retrieve

log = logging.getLogger(__name__)


class CitationAnswer(BaseModel):
    answer: str
    citation_ids: list[str] = Field(default_factory=list)
    # Second safety net: the model may only ever send a question TO a doctor, never away from one.
    needs_doctor: bool = False


@dataclass(frozen=True)
class RecordsAnswer:
    status: str
    answer: str
    citations: list[RetrievedChunk]


# Questions asking for medical advice (medicines, doses, treatment, a diagnosis) go to a doctor before any
# model sees them. Reading a value off the report ("what was my LDL", "was my vitamin D low") stays
# answerable. Measured by `make eval` on evals/sets/records_doctor_review.jsonl (recall must be 100%).
_DOCTOR_REVIEW = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bdiagnos",
        r"\bprescri",
        r"\bdos(?:e|es|age|ing)\b",
        r"\bhow (?:much|many|often|long)\b.*\b(?:take|use|continue|eat|drink)\b",
        r"\b(?:tablet|pill|capsule|injection|medicine)s?\b.*\bshould i\b",
        r"\bshould i\b.*\b(?:take|start|stop|continue|increase|reduce|decrease|change|skip|switch)\b",
        r"\bshould i\b.*\b(?:worry|be worried|be concerned)\b",
        r"\b(?:can|may) i\b.*\b(?:take|stop|skip|start|continue|drink|eat)\b",
        r"\b(?:which|what|any) (?:medicine|medication|tablet|drug|pill|treatment|supplement)s?\b",
        r"\b(?:treat|treatment|cure|remedy|remedies)\b",
        r"\bdo i (?:have|need)\b",
        r"\bam i (?:diabetic|sick|ill|at risk)\b",
        r"\bis (?:it|this|that) (?:serious|dangerous|cancer)\b",
        r"\b(?:kitni|kitna|kaunsi|kaun si|konsi)\b.*\b(?:goli|dawai|dawa|tablet|medicine)\b",
        r"\b(?:goli|dawai|dawa)\b.*\b(?:lu|loon|lun|lena|leni|khau|khaun|khani|band)\b",
        r"\b(?:ilaaj|ilaj|upchar)\b",
    )
)


def needs_doctor_review(question: str) -> bool:
    lowered = " ".join(question.lower().split())
    return any(pattern.search(lowered) for pattern in _DOCTOR_REVIEW)


def _prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    context = "\n\n".join(
        f"[C{index}] document={chunk.doc_id} page={chunk.page}\n{chunk.text}"
        for index, chunk in enumerate(chunks, start=1)
    )
    return (
        "Answer only from the cited context. Return citation_ids that exactly match bracketed chunk ids."
        f"\n\nQuestion: {question}\n\nContext:\n{context}"
    )


async def answer_question(
    pool: AsyncConnectionPool,
    chat: EgressChatClient,
    auth: AuthContext,
    *,
    question: str,
    patient_id: str | None = None,
    trace_id: str | None = None,
) -> RecordsAnswer:
    if needs_doctor_review(question):
        return RecordsAnswer(
            status="needs_doctor",
            answer="This question needs a doctor to review it.",
            citations=[],
        )
    # A patient always asks about their own record; anyone else must say whose record they mean.
    target = auth["acting_for_patient_id"] if auth["role"] == "patient" else patient_id
    if target is None:
        return RecordsAnswer(
            status="patient_required", answer="Choose whose records you are asking about.", citations=[]
        )
    chunks = await retrieve(pool, auth, question=question, patient_id=target)
    if not chunks:
        return RecordsAnswer(
            status="insufficient_evidence", answer="I could not find this in your records.", citations=[]
        )
    by_citation_id = {f"C{index}": chunk for index, chunk in enumerate(chunks, start=1)}
    try:
        model_answer = await chat.ask_structured(
            ModelRequest(
                system=(
                    "You answer patient record questions with verified citations. Never diagnose. "
                    "Report what the record says, including its own flags such as 'high'. If the question "
                    "asks for advice on medicines, doses, treatment, or whether they have a condition, set "
                    "needs_doctor=true and leave the answer empty."
                ),
                user=_prompt(question, chunks),
                purpose="records qa",
            ),
            CitationAnswer,
        )
    except (ModelUnavailable, EgressBlocked, BlockedIdentifier) as exc:
        # Never a 500 for the patient: the model is down, refused, or the privacy gate said no.
        log.warning("records answer unavailable: %s %s", type(exc).__name__, exc)
        return RecordsAnswer(
            status="unavailable",
            answer="I can't answer that right now. Please try again later, or ask the records desk.",
            citations=[],
        )
    if model_answer.needs_doctor:
        return RecordsAnswer(
            status="needs_doctor",
            answer="This question needs a doctor to review it.",
            citations=[],
        )
    if not model_answer.citation_ids or not set(model_answer.citation_ids) <= set(by_citation_id):
        return RecordsAnswer(
            status="insufficient_evidence",
            answer="I could not verify the answer against your records.",
            citations=[],
        )
    cited = [by_citation_id[citation_id] for citation_id in model_answer.citation_ids]
    async with scoped(pool, auth) as conn:
        for chunk in cited:
            await audit.write(
                conn,
                auth,
                action="read",
                resource="document",
                record_id=chunk.doc_id,
                patient_id=chunk.patient_id,
                purpose="records qa",
                trace_id=trace_id,  # links each read to the run (or assistant conversation) behind it
            )
    return RecordsAnswer(status="answered", answer=model_answer.answer, citations=cited)
