"""Records question answering with verified citations."""

from dataclasses import dataclass

from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from services.platform import audit
from services.platform.auth import AuthContext
from services.platform.db import scoped
from services.platform.egress.client import EgressChatClient, ModelRequest

from .retrieval import RetrievedChunk, retrieve


class CitationAnswer(BaseModel):
    answer: str
    citation_ids: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class RecordsAnswer:
    status: str
    answer: str
    citations: list[RetrievedChunk]


_DOCTOR_REVIEW_TERMS = ("diagnose", "diagnosis", "dose", "dosage", "prescribe", "increase medicine")


def needs_doctor_review(question: str) -> bool:
    lowered = question.lower()
    return any(term in lowered for term in _DOCTOR_REVIEW_TERMS)


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
) -> RecordsAnswer:
    if needs_doctor_review(question):
        return RecordsAnswer(
            status="needs_doctor",
            answer="This question needs a doctor to review it.",
            citations=[],
        )
    chunks = await retrieve(pool, auth, question=question)
    if not chunks:
        return RecordsAnswer(
            status="insufficient_evidence", answer="I could not find this in your records.", citations=[]
        )
    by_citation_id = {f"C{index}": chunk for index, chunk in enumerate(chunks, start=1)}
    model_answer = await chat.ask_structured(
        ModelRequest(
            system="You answer patient record questions with verified citations. Never diagnose.",
            user=_prompt(question, chunks),
            purpose="records qa",
        ),
        CitationAnswer,
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
            )
    return RecordsAnswer(status="answered", answer=model_answer.answer, citations=cited)
