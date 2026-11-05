"""Scribe graph behaviour with fake tools and the in-memory checkpointer."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from services.agent.scribe.graph import MAX_REDRAFTS, build_scribe_graph
from services.platform.auth import AuthContext
from services.platform.egress.client import ModelUnavailable
from services.scribe.service import SoapDraft
from services.scribe.stock import StockFlag

DOCTOR: AuthContext = {"user_id": "u-doc", "role": "doctor", "acting_for_patient_id": None}
TRANSCRIPT = (
    "Doctor: chest tightness on stairs, BP 138/86. Start atorvastatin 10 mg at night and continue metformin. "
    "ECG and lipid panel, review in two weeks."
)
OUT_OF_STOCK = {"Metformin"}


class FakeScribeTools:
    def __init__(self, *, model_medicines=None, unavailable=False):
        self.model_medicines = model_medicines or ["Atorvastatin"]
        self.unavailable = unavailable
        self.draft_calls: list[str | None] = []
        self.stock_calls: list[list[str]] = []
        self.signed: list[dict] = []

    async def draft(self, *, transcript, comments):
        self.draft_calls.append(comments)
        if self.unavailable:
            raise ModelUnavailable("model_call_failed")
        return SoapDraft(
            subjective="Chest tightness on exertion.",
            objective="BP 138/86.",
            assessment="As stated by the doctor.",
            plan="Atorvastatin 10 mg at night; ECG; lipid panel; review in two weeks.",
            medicines=self.model_medicines,
        )

    async def formulary(self):
        return ["Atorvastatin", "Metformin", "Amlodipine"]

    async def stock(self, auth, *, encounter_id, medicines):
        self.stock_calls.append(list(medicines))
        return [
            StockFlag(
                m, "out_of_stock" if m in OUT_OF_STOCK else "in_stock", qty=0 if m in OUT_OF_STOCK else 9
            )
            for m in medicines
        ]

    async def sign(self, auth, *, encounter_id, draft, soap, edit_history, medicines, transcript):
        self.signed.append({"soap": soap, "history": edit_history, "medicines": medicines})
        return {"note_id": "n1", "version": 1, "content_hash": "h"}


def graph(tools):
    return build_scribe_graph(tools).compile(checkpointer=InMemorySaver())


CFG = {"configurable": {"thread_id": "t1"}}


async def start(g):
    return await g.ainvoke({"auth": DOCTOR, "encounter_id": "e1", "transcript": TRANSCRIPT}, CFG)


def review(out):
    [intr] = out["__interrupt__"]
    assert intr.value["type"] == "review_note"
    return intr.value


async def test_draft_pauses_for_review_with_grounded_medicines_and_stock_flags():
    tools = FakeScribeTools()
    value = review(await start(graph(tools)))
    assert value["medicines"] == ["Atorvastatin", "Metformin"]  # both named in the transcript
    assert {f["medicine"]: f["status"] for f in value["stock_flags"]} == {
        "Atorvastatin": "in_stock",
        "Metformin": "out_of_stock",
    }
    assert tools.signed == []  # nothing persisted before the signature


async def test_model_medicine_absent_from_transcript_is_rejected_and_shown():
    tools = FakeScribeTools(model_medicines=["Atorvastatin", "Rosuvastatin"])
    value = review(await start(graph(tools)))
    assert "Rosuvastatin" not in value["medicines"]
    assert value["rejected_medicines"] == ["Rosuvastatin"]


async def test_model_outage_still_gives_the_doctor_a_note_to_write():
    tools = FakeScribeTools(unavailable=True)
    value = review(await start(graph(tools)))
    assert value["drafting_unavailable"] is True
    assert value["soap"]["plan"] == ""
    assert value["medicines"] == ["Atorvastatin", "Metformin"]  # still grounded by code


async def test_edit_rechecks_stock_then_sign_persists_note_prescriptions_and_history():
    tools = FakeScribeTools()
    g = graph(tools)
    soap = review(await start(g))["soap"]
    edited = {
        **soap,
        "plan": "Atorvastatin 10 mg; switch metformin to amlodipine",
        "medicines": ["Atorvastatin", "Amlodipine"],
    }
    value = review(await g.ainvoke(Command(resume={"action": "edit", "soap": edited}), CFG))
    assert tools.stock_calls[-1] == ["Atorvastatin", "Amlodipine"]  # stock re-checked after the edit
    assert {f["medicine"] for f in value["stock_flags"]} == {"Atorvastatin", "Amlodipine"}
    done = await g.ainvoke(Command(resume={"action": "sign", "soap": edited}), CFG)
    assert done["outcome"] == "signed"
    [signed] = tools.signed
    assert signed["medicines"] == ["Atorvastatin", "Amlodipine"]
    assert [h["action"] for h in signed["history"]] == ["edit", "sign"]
    assert "medicines" in signed["history"][0]["fields"]


async def test_reject_redrafts_with_comments_up_to_a_cap():
    tools = FakeScribeTools()
    g = graph(tools)
    await start(g)
    for i in range(MAX_REDRAFTS + 1):
        await g.ainvoke(Command(resume={"action": "reject", "comments": f"try {i}"}), CFG)
    assert tools.draft_calls == [None, "try 0", "try 1"]  # the third rejection does not redraft again
    assert tools.signed == []


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"action": "approve"},
        {"action": "sign"},
        {"action": "sign", "soap": {"subjective": "x"}},
        {
            "action": "edit",
            "soap": {"subjective": "", "objective": "", "assessment": "", "plan": "", "medicines": [""]},
        },
    ],
)
async def test_invalid_decisions_ask_again_and_never_sign(bad):
    tools = FakeScribeTools()
    g = graph(tools)
    await start(g)
    review(await g.ainvoke(Command(resume=bad), CFG))
    assert tools.signed == []


@pytest.mark.parametrize("action", ["sign", "edit"])
def test_api_refuses_sign_or_edit_without_the_note(action):
    from pydantic import ValidationError

    from services.api.routers.scribe import ReviewIn

    with pytest.raises(ValidationError):
        ReviewIn(action=action)
    assert ReviewIn(action="reject").soap is None
