"""W1 slice-0 graph behaviour with fake tools and the in-memory checkpointer (no Docker needed)."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from services.agent.w1_triage.graph import EMERGENCY_REPLY, MAX_REOFFERS, build_w1
from services.agent.w1_triage.state import CandidateView
from services.platform.auth import AuthContext

PRIYA: AuthContext = {"user_id": "u-priya", "role": "patient", "acting_for_patient_id": "p-priya"}


def cand(slot: str, doctor: str = "d1") -> CandidateView:
    return CandidateView(
        doctor_id=doctor,
        doctor_name=f"Dr {doctor}",
        slot_id=slot,
        clinic_name="Baner",
        starts_at="2026-11-03T10:00:00+05:30",
    )


class FakeDeps:
    def __init__(self, slots: list[CandidateView], full: set[str] | None = None) -> None:
        self.slots = slots
        self.full = full or set()
        self.bookings: dict[str, str] = {}  # idempotency_key -> slot_id
        self.handoffs: list[dict] = []
        self.shortlist_calls = 0

    async def shortlist(self, specialty, exclude_slot_ids):
        self.shortlist_calls += 1
        return [s for s in self.slots if s["slot_id"] not in exclude_slot_ids][:3]

    async def reserve(self, auth, *, slot_id, patient_id, idempotency_key, thread_id):
        if idempotency_key in self.bookings:
            return f"appt-{idempotency_key}"
        if slot_id in self.full:
            return None
        self.bookings[idempotency_key] = slot_id
        return f"appt-{idempotency_key}"

    async def open_handoff(self, auth, *, kind, patient_id, reason, thread_id):
        self.handoffs.append({"kind": kind, "patient_id": patient_id, "reason": reason})
        return f"ticket-{len(self.handoffs)}"


def app(deps: FakeDeps):
    return build_w1(deps).compile(checkpointer=InMemorySaver())


def cfg(thread: str = "t1") -> dict:
    return {"configurable": {"thread_id": thread}}


async def start(graph, text: str, thread: str = "t1"):
    return await graph.ainvoke({"auth": PRIYA, "intake_text": text}, cfg(thread))


async def test_red_flag_ends_in_emergency_handoff_without_booking():
    deps = FakeDeps([cand("s1")])
    out = await start(app(deps), "My mother has chest pain and is breathless since morning")

    assert out["outcome"] == "emergency"
    assert out["reply"] == EMERGENCY_REPLY
    assert "__interrupt__" not in out
    assert deps.handoffs == [
        {"kind": "emergency", "patient_id": "p-priya", "reason": "stub_breathless,stub_chest_pain"}
    ]
    assert deps.shortlist_calls == 0 and deps.bookings == {}


async def test_routine_intake_pauses_with_candidates_then_books_on_resume():
    deps = FakeDeps([cand("s1", "d1"), cand("s2", "d2")])
    graph = app(deps)

    paused = await start(graph, "Dull lower back pain for three weeks")
    [intr] = paused["__interrupt__"]
    assert intr.value["type"] == "pick_slot"
    assert [c["slot_id"] for c in intr.value["candidates"]] == ["s1", "s2"]

    done = await graph.ainvoke(Command(resume={"slot_id": "s2", "idempotency_key": "k1"}), cfg())
    assert done["outcome"] == "booked"
    assert done["booking_id"] == "appt-k1"
    assert deps.bookings == {"k1": "s2"}
    assert deps.shortlist_calls == 1  # resume did not re-run the side-effecting shortlist


async def test_choice_outside_offered_slots_is_rejected_and_asked_again():
    deps = FakeDeps([cand("s1")])
    graph = app(deps)
    await start(graph, "Knee pain")

    bad_choice = {"slot_id": "someone-elses-slot", "idempotency_key": "k"}
    again = await graph.ainvoke(Command(resume=bad_choice), cfg())
    assert "__interrupt__" in again
    assert deps.bookings == {}


async def test_full_slot_is_excluded_and_reoffered():
    deps = FakeDeps([cand("s1", "d1"), cand("s2", "d2")], full={"s1"})
    graph = app(deps)
    await start(graph, "Knee pain")

    reoffer = await graph.ainvoke(Command(resume={"slot_id": "s1", "idempotency_key": "k1"}), cfg())
    [intr] = reoffer["__interrupt__"]
    assert [c["slot_id"] for c in intr.value["candidates"]] == ["s2"]

    done = await graph.ainvoke(Command(resume={"slot_id": "s2", "idempotency_key": "k2"}), cfg())
    assert done["outcome"] == "booked"


async def test_no_slots_goes_to_front_desk():
    deps = FakeDeps([])
    out = await start(app(deps), "Knee pain")
    assert out["outcome"] == "front_desk"
    assert deps.handoffs[0]["kind"] == "front_desk"


async def test_repeated_full_slots_end_at_front_desk():
    slots = [cand(f"s{i}", f"d{i}") for i in range(MAX_REOFFERS + 1)]
    deps = FakeDeps(slots, full={s["slot_id"] for s in slots})
    graph = app(deps)
    out = await start(graph, "Knee pain")
    for i in range(MAX_REOFFERS):
        out = await graph.ainvoke(Command(resume={"slot_id": f"s{i}", "idempotency_key": f"k{i}"}), cfg())
    assert out["outcome"] == "front_desk"
    assert deps.handoffs[-1]["reason"] == "too_many_reoffers"


@pytest.mark.parametrize("text", ["seene mein dard ho raha hai", "He FAINTED at work"])
async def test_stub_red_flags_cover_hinglish_and_case(text):
    out = await start(app(FakeDeps([cand("s1")])), text)
    assert out["outcome"] == "emergency"
