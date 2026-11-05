"""Supervisor: routing, parallel fan-out, safety first, role limits and audit linkage."""

import asyncio
import itertools

import pytest

from services.agent.supervisor.graph import build_supervisor_graph, split_clauses
from services.platform.egress.client import ModelUnavailable
from services.platform.tracing import MemorySpanSink, trace_run

PATIENT = {"user_id": "u-p", "role": "patient", "acting_for_patient_id": "p1"}
CAREGIVER = {"user_id": "u-c", "role": "caregiver", "acting_for_patient_id": None}
DOCTOR = {"user_id": "u-d", "role": "doctor", "acting_for_patient_id": None}
DESK = {"user_id": "u-k", "role": "desk", "acting_for_patient_id": None}


class FakeSpecialists:
    def __init__(self, *, fail: str | None = None, barrier: int = 0) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.audits: list[dict] = []
        self.fail = fail
        self._ids = (f"d{i}" for i in itertools.count(1))
        self._barrier = barrier
        self._started = 0
        self._all_started = asyncio.Event()

    async def _arrive(self) -> None:
        # With a barrier, every specialist must be running at once or this times out: proves parallelism.
        if self._barrier:
            self._started += 1
            if self._started >= self._barrier:
                self._all_started.set()
            await asyncio.wait_for(self._all_started.wait(), timeout=2)

    def new_id(self) -> str:
        return next(self._ids)

    async def audit(self, auth, *, specialist, delegation_id, trace_id, patient_id):
        self.audits.append(
            {"specialist": specialist, "id": delegation_id, "trace": trace_id, "patient": patient_id}
        )

    async def triage(self, auth, *, text, thread_id):
        self.calls.append(("triage", {"text": text, "thread_id": thread_id}))
        await self._arrive()
        if self.fail == "triage":
            raise RuntimeError("boom")
        if "chest" in text:
            return {"status": "emergency", "thread_id": thread_id, "reply": "Call 112 now."}
        return {"status": "awaiting_safety_check", "thread_id": thread_id, "reply": "Safety questions first."}

    async def records(self, auth, *, question, patient_id, encounter_id, trace_id):
        self.calls.append(("records", {"question": question, "patient_id": patient_id}))
        await self._arrive()
        if self.fail == "records":
            raise RuntimeError("boom")
        return {"status": "answered", "reply": "Your LDL was 162 mg/dL.", "citations": [{"page": 1}]}

    async def visit(self, auth, *, thread_id, question):
        self.calls.append(("visit", {"thread_id": thread_id, "question": question}))
        return {"status": "booked", "reply": "Your appointment is with Dr Ranade, Orthopaedics."}

    async def scribe(self, auth, *, encounter_id, transcript, thread_id):
        self.calls.append(("scribe", {"encounter_id": encounter_id, "thread_id": thread_id}))
        await self._arrive()
        return {"status": "awaiting_review", "thread_id": thread_id, "reply": "Draft ready."}


class FixedPlanner:
    def __init__(self, routes=None, error: Exception | None = None) -> None:
        self.routes = routes or []
        self.error = error
        self.calls = 0

    async def assign(self, clauses, allowed):
        self.calls += 1
        if self.error:
            raise self.error
        return self.routes


async def run(specialists, auth, message, planner=None, **extra):
    graph = build_supervisor_graph(specialists, planner).compile()
    return await graph.ainvoke(
        {"auth": auth, "trace_id": "T1", "message": message, "results": [], **extra},
        {"max_concurrency": 3},
    )


TWO_PART = "I have had knee pain for a week. Also what was my LDL in the last report?"


async def test_two_requests_fan_out_in_parallel_and_reply_in_the_order_asked():
    sp = FakeSpecialists(barrier=2)
    out = await run(sp, PATIENT, TWO_PART)
    assert out["planned_by"] == "rules"
    assert [r["specialist"] for r in sorted(out["results"], key=lambda r: r["order"])] == [
        "triage",
        "records",
    ]
    assert out["reply"] == "Safety questions first.\n\nYour LDL was 162 mg/dL."
    assert out["outcome"] == "delegated"


async def test_patient_emergency_goes_to_triage_alone_before_any_model():
    sp, planner = FakeSpecialists(), FixedPlanner([(0, "records")])
    out = await run(sp, PATIENT, "crushing chest pain right now, and what was my LDL?", planner)
    assert planner.calls == 0  # the model never saw the message
    assert out["planned_by"] == "safety"
    assert [c[0] for c in sp.calls] == ["triage"]
    assert sp.calls[0][1]["text"] == "crushing chest pain right now, and what was my LDL?"
    assert out["outcome"] == "emergency"


async def test_model_plan_is_used_but_cannot_exceed_the_role_or_invent_clauses():
    sp = FakeSpecialists()
    planner = FixedPlanner([(0, "triage"), (1, "records"), (1, "scribe"), (7, "records")])
    out = await run(sp, PATIENT, TWO_PART, planner)
    assert out["planned_by"] == "model"
    assert sorted(c[0] for c in sp.calls) == ["records", "triage"]  # scribe and clause 7 dropped


async def test_specialists_get_the_patients_own_words_never_model_text():
    sp = FakeSpecialists()
    await run(sp, PATIENT, TWO_PART, FixedPlanner([(0, "triage"), (1, "records")]))
    requests = {name: args.get("text") or args.get("question") for name, args in sp.calls}
    assert requests == {
        "triage": "I have had knee pain for a week.",
        "records": "Also what was my LDL in the last report?",
    }


@pytest.mark.parametrize("planner", [FixedPlanner(error=ModelUnavailable("down")), FixedPlanner([])])
async def test_planner_failure_or_empty_plan_falls_back_to_rules(planner):
    sp = FakeSpecialists()
    out = await run(sp, PATIENT, TWO_PART, planner)
    assert out["planned_by"] == "rules"
    assert sorted(c[0] for c in sp.calls) == ["records", "triage"]


async def test_unclear_patient_message_still_reaches_triage():
    sp = FakeSpecialists()
    out = await run(sp, PATIENT, "hello there")
    assert [c[0] for c in sp.calls] == ["triage"]  # triage asks its clarifying question
    assert out["outcome"] == "delegated"


async def test_caregiver_gets_records_for_the_named_patient_but_never_triage():
    sp = FakeSpecialists()
    await run(sp, CAREGIVER, TWO_PART, patient_id="p9")
    assert [c[0] for c in sp.calls] == ["records"]
    assert sp.calls[0][1]["patient_id"] == "p9"


async def test_doctor_transcript_drafts_a_note_and_records_run_alongside():
    sp = FakeSpecialists(barrier=2)
    out = await run(
        sp,
        DOCTOR,
        "what was the last HbA1c result?",
        encounter_id="e1",
        transcript="Doctor: sugar is high. Start metformin 500 mg twice daily.",
    )
    assert sorted(c[0] for c in sp.calls) == ["records", "scribe"]
    assert out["outcome"] == "delegated"


async def test_doctor_without_a_consultation_gets_guidance_not_a_patient_search():
    sp = FakeSpecialists()
    out = await run(sp, DOCTOR, "what was the last HbA1c result?")
    assert sp.calls == []
    assert out["outcome"] == "front_desk"


async def test_desk_role_is_not_served_by_the_assistant():
    sp = FakeSpecialists()
    out = await run(sp, DESK, TWO_PART)
    assert sp.calls == [] and out["outcome"] == "front_desk"


async def test_one_failing_specialist_does_not_sink_the_others():
    sp = FakeSpecialists(fail="records")
    out = await run(sp, PATIENT, TWO_PART)
    by = {r["specialist"]: r for r in out["results"]}
    assert by["records"]["status"] == "failed" and by["records"]["error_type"] == "RuntimeError"
    assert by["triage"]["status"] == "awaiting_safety_check"


async def test_every_delegation_is_audited_with_the_specialists_thread_and_the_supervisor_trace():
    sp = FakeSpecialists()
    out = await run(sp, PATIENT, TWO_PART)
    assert {a["specialist"] for a in sp.audits} == {"triage", "records"}
    assert all(a["trace"] == "T1" and a["patient"] == "p1" for a in sp.audits)
    triage_audit = next(a for a in sp.audits if a["specialist"] == "triage")
    triage_call = next(args for name, args in sp.calls if name == "triage")
    assert triage_call["thread_id"] == triage_audit["id"]
    triage_result = next(r for r in out["results"] if r["specialist"] == "triage")
    assert triage_result["delegation_id"] == triage_audit["id"]


async def test_supervisor_nodes_are_traced_under_one_trace_without_message_text():
    sink, sp = MemorySpanSink(), FakeSpecialists()
    graph = build_supervisor_graph(sp).compile()
    async with trace_run("assistant", "T1", sink) as callbacks:
        await graph.ainvoke(
            {"auth": PATIENT, "trace_id": "T1", "message": TWO_PART, "results": []},
            {"callbacks": callbacks},
        )
    names = [s.name for s in sink.spans]
    assert {"screen", "plan", "delegate", "combine"} <= set(names)
    assert names.count("delegate") == 2
    assert all(s.trace_id == "T1" for s in sink.spans)
    assert "knee" not in repr(sink.spans)


def test_clauses_split_on_sentences_and_new_questions_but_not_symptom_lists():
    assert split_clauses("knee pain and swelling") == ["knee pain and swelling"]
    assert split_clauses("pet mein jalan hai, aur mera vitamin D kitna tha?") == [
        "pet mein jalan hai",
        "mera vitamin D kitna tha?",
    ]
    assert split_clauses("sir dard aur bukhar hai") == ["sir dard aur bukhar hai"]
    assert split_clauses("fever since monday and what was my hba1c") == [
        "fever since monday",
        "what was my hba1c",
    ]


async def test_a_follow_up_about_this_chats_booking_is_answered_from_it_not_from_records():
    sp = FakeSpecialists()
    out = await run(sp, PATIENT, "what is the doctor specialization?", conversation_thread_id="triage-1")
    assert [c[0] for c in sp.calls] == ["visit"]
    assert sp.calls[0][1]["thread_id"] == "triage-1"
    assert "Orthopaedics" in out["reply"]


async def test_without_a_booking_in_the_chat_there_is_no_visit_to_ask_about():
    sp = FakeSpecialists()
    # Even if the model says "visit", there is no conversation to answer from.
    await run(sp, PATIENT, "which doctor is it?", FixedPlanner([(0, "visit")]))
    assert "visit" not in [c[0] for c in sp.calls]


async def test_a_new_symptom_in_a_follow_up_still_goes_to_triage():
    sp = FakeSpecialists()
    await run(
        sp,
        PATIENT,
        "Which clinic is it at? Also I now have a fever and cough.",
        conversation_thread_id="triage-1",
    )
    assert sorted(c[0] for c in sp.calls) == ["triage", "visit"]


async def test_asking_for_other_times_continues_the_booking_even_if_the_model_says_triage():
    # A new triage would ask the safety questions again and forget the doctors already offered.
    sp = FakeSpecialists()
    await run(
        sp,
        PATIENT,
        "Need other timing slots for chetan doctor",
        FixedPlanner([(0, "triage")]),
        conversation_thread_id="triage-1",
    )
    assert [c[0] for c in sp.calls] == ["visit"]
