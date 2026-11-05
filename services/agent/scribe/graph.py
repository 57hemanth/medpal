"""Consultation scribe graph: the doctor reviews every draft; nothing persists before the signature.

    draft_note → ground_medicines → stock_check → review  (interrupt: doctor decides)
         ▲                              ▲            │
         │ reject (with comments)       │ edit       ├─ edit ───► stock_check (medicines may have changed)
         └──────────────────────────────┼────────────┤
                                        │            └─ sign ───► persist (note + prescriptions) ─► END

* The model only structures; medicines must be named in the transcript or the doctor's own edit.
* If the model is unavailable the doctor gets an empty draft to write by hand; the flow still works.
* `review` calls interrupt(), so it re-runs on resume and must stay side-effect free.
"""

from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from services.platform.auth import AuthContext
from services.platform.egress.client import ModelUnavailable
from services.platform.phi.scrubber import BlockedIdentifier, EgressBlocked
from services.scribe.service import SoapDraft
from services.scribe.stock import StockFlag, ground_medicines

MAX_REDRAFTS = 2
SOAP_FIELDS = ("subjective", "objective", "assessment", "plan")


class ScribeTools(Protocol):
    def draft(self, *, transcript: str, comments: str | None) -> Awaitable[SoapDraft]: ...

    def formulary(self) -> Awaitable[list[str]]: ...

    def stock(
        self, auth: AuthContext, *, encounter_id: str, medicines: list[str]
    ) -> Awaitable[list[StockFlag]]: ...

    def sign(
        self,
        auth: AuthContext,
        *,
        encounter_id: str,
        draft: SoapDraft,
        soap: dict[str, Any],
        edit_history: list[dict[str, Any]],
        medicines: list[str],
        transcript: str,
    ) -> Awaitable[dict[str, Any]]: ...


class ScribeState(TypedDict, total=False):
    auth: AuthContext
    encounter_id: str
    transcript: str
    comments: str | None
    draft: dict[str, Any]  # what the model proposed (kept for edit distance)
    soap: dict[str, Any]  # what the doctor is reviewing now (draft, then their edits)
    medicines: list[str]
    rejected_medicines: list[str]
    stock_flags: list[dict[str, Any]]
    drafting_unavailable: bool
    decision: dict[str, Any] | None
    redrafts: int
    edit_history: list[dict[str, Any]]
    signed: dict[str, Any] | None
    outcome: Literal["signed"] | None


def _valid_soap(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not all(isinstance(value.get(k), str) for k in SOAP_FIELDS):
        return None
    meds = value.get("medicines", [])
    if not isinstance(meds, list) or not all(isinstance(m, str) and m.strip() for m in meds):
        return None
    return {**{k: value[k] for k in SOAP_FIELDS}, "medicines": [m.strip() for m in meds]}


def build_scribe_graph(tools: ScribeTools) -> StateGraph:
    async def draft_note(state: ScribeState) -> ScribeState:
        try:
            draft = await tools.draft(transcript=state["transcript"], comments=state.get("comments"))
            unavailable = False
        except (ModelUnavailable, EgressBlocked, BlockedIdentifier):
            # The doctor can always write the note by hand; the model is a convenience, not a dependency.
            draft, unavailable = SoapDraft(subjective="", objective="", assessment="", plan=""), True
        data = draft.model_dump()
        return {"draft": data, "soap": data, "drafting_unavailable": unavailable, "decision": None}

    async def ground(state: ScribeState) -> ScribeState:
        grounded, rejected = ground_medicines(
            state["transcript"], state["draft"].get("medicines", []), await tools.formulary()
        )
        return {
            "medicines": grounded,
            "rejected_medicines": rejected,
            "soap": {**state["soap"], "medicines": grounded},
        }

    async def stock_check(state: ScribeState) -> ScribeState:
        flags = await tools.stock(
            state["auth"], encounter_id=state["encounter_id"], medicines=state["medicines"]
        )
        return {"stock_flags": [f.as_dict() for f in flags]}

    async def review(state: ScribeState) -> ScribeState:
        # Pure: re-runs on resume.
        decision = interrupt(
            {
                "type": "review_note",
                "soap": state["soap"],
                "medicines": state["medicines"],
                "stock_flags": state["stock_flags"],
                "rejected_medicines": state.get("rejected_medicines", []),
                "drafting_unavailable": state.get("drafting_unavailable", False),
            }
        )
        if not isinstance(decision, dict) or decision.get("action") not in ("sign", "edit", "reject"):
            return {"decision": None}
        if decision["action"] in ("sign", "edit"):
            soap = _valid_soap(decision.get("soap"))
            if soap is None:
                return {"decision": None}
            return {"decision": {"action": decision["action"], "soap": soap}}
        return {"decision": {"action": "reject", "comments": str(decision.get("comments") or "")[:2000]}}

    async def apply_edit(state: ScribeState) -> ScribeState:
        soap = state["decision"]["soap"]  # type: ignore[index]
        changed = [k for k in (*SOAP_FIELDS, "medicines") if soap.get(k) != state["soap"].get(k)]
        history = [*state.get("edit_history", []), _event("edit", fields=changed)]
        # The doctor's own medicine list is authoritative: they are the prescriber.
        return {"soap": soap, "medicines": soap["medicines"], "edit_history": history}

    async def apply_reject(state: ScribeState) -> ScribeState:
        comments = state["decision"]["comments"]  # type: ignore[index]
        history = [*state.get("edit_history", []), _event("reject", comments=bool(comments))]
        return {"comments": comments, "redrafts": state.get("redrafts", 0) + 1, "edit_history": history}

    async def persist(state: ScribeState) -> ScribeState:
        soap = state["decision"]["soap"]  # type: ignore[index]
        changed = [k for k in (*SOAP_FIELDS, "medicines") if soap.get(k) != state["soap"].get(k)]
        history = [*state.get("edit_history", []), _event("sign", fields=changed)]
        signed = await tools.sign(
            state["auth"],
            encounter_id=state["encounter_id"],
            draft=SoapDraft(**state["draft"]),
            soap=soap,
            edit_history=history,
            medicines=soap["medicines"],
            transcript=state["transcript"],
        )
        return {"signed": signed, "outcome": "signed", "edit_history": history}

    def after_review(state: ScribeState) -> str:
        decision = state.get("decision")
        if decision is None:
            return "review"
        if decision["action"] == "sign":
            return "persist"
        if decision["action"] == "edit":
            return "apply_edit"
        return "apply_reject"

    def after_reject(state: ScribeState) -> str:
        return "draft_note" if state.get("redrafts", 0) <= MAX_REDRAFTS else "review"

    g = StateGraph(ScribeState)
    g.add_node("draft_note", draft_note)
    g.add_node("ground", ground)
    g.add_node("stock_check", stock_check)
    g.add_node("review", review)
    g.add_node("apply_edit", apply_edit)
    g.add_node("apply_reject", apply_reject)
    g.add_node("persist", persist)
    g.add_edge(START, "draft_note")
    g.add_edge("draft_note", "ground")
    g.add_edge("ground", "stock_check")
    g.add_edge("stock_check", "review")
    g.add_conditional_edges("review", after_review, ["review", "persist", "apply_edit", "apply_reject"])
    g.add_edge("apply_edit", "stock_check")
    g.add_conditional_edges("apply_reject", after_reject, ["draft_note", "review"])
    g.add_edge("persist", END)
    return g


def _event(action: str, **details: object) -> dict[str, Any]:
    return {"action": action, "at": datetime.now(UTC).isoformat(), **details}
