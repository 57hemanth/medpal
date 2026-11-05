"""Model planner for the supervisor: labels numbered clauses, nothing more.

The model sees the clauses de-identified (through the egress client) and returns only
(clause number, specialist) pairs. It never writes the text a specialist receives.
"""

from typing import Literal

from pydantic import BaseModel, Field

from services.platform.egress.client import EgressChatClient, ModelRequest

SYSTEM = (
    "You route parts of a clinic assistant message to specialists. For each numbered clause choose one: "
    "'triage' (symptoms, wanting to see or book a doctor), 'records' (questions about the person's own "
    "medical reports, lab results or uploaded documents), 'scribe' (a doctor asking to draft or write up "
    "the consultation note), 'visit' (a follow-up about the appointment already found or booked in this "
    "conversation: which doctor, their specialty, the clinic, the time, or asking for other times or "
    "days), or 'none'. "
    "Only use specialists from the allowed list. Never diagnose. "
    "Return one route per clause number."
)


class ClauseRoute(BaseModel):
    clause: int = Field(ge=0)
    specialist: Literal["triage", "records", "scribe", "visit", "none"]


class RoutePlan(BaseModel):
    routes: list[ClauseRoute]


class ModelPlanner:
    def __init__(self, chat: EgressChatClient) -> None:
        self._chat = chat

    async def assign(self, clauses: list[str], allowed: frozenset[str]) -> list[tuple[int, str]]:
        numbered = "\n".join(f"{i}: {clause}" for i, clause in enumerate(clauses))
        plan = await self._chat.ask_structured(
            ModelRequest(
                system=SYSTEM,
                user=f"Allowed specialists: {', '.join(sorted(allowed)) or 'none'}\n\nClauses:\n{numbered}",
                purpose="assistant routing",
                tier="small",
            ),
            RoutePlan,
        )
        return [(r.clause, r.specialist) for r in plan.routes]
