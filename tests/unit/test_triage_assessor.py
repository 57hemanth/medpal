"""The model step inside triage: what it may do, when it runs, and what code never lets it do."""

import asyncio

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from data.synthetic.reference import SPECIALTIES as NETWORK_SPECIALTIES
from services.agent.triage.assessor import Assessment, ModelAssessor, SpecialtyGuess
from services.agent.triage.graph import build_triage_graph
from services.agent.triage.specialties import SPECIALTIES
from services.platform.egress.client import EgressChatClient
from services.platform.egress.providers import FakeChatModel
from tests.unit.test_triage_graph import ALL_NO, ASHA, FakeTriageTools, cand, cfg


class FakeAssessor:
    def __init__(self, flags=(), guess: SpecialtyGuess | None = None, skipped: str | None = None) -> None:
        self.result = Assessment(list(flags), guess, skipped)
        self.calls: list[str] = []
        self.prefetched: list[str] = []

    def prefetch(self, key, text):
        self.prefetched.append(text)

    async def assess(self, text, *, key=None):
        self.calls.append(text)
        return self.result


def graph(tools, assessor):
    return build_triage_graph(tools, assessor).compile(checkpointer=InMemorySaver())


async def run(g, text):
    out = await g.ainvoke({"auth": ASHA, "intake_text": text}, cfg())
    interrupts = out.get("__interrupt__") or []
    if interrupts and interrupts[0].value["type"] == "safety_check":
        out = await g.ainvoke(Command(resume={"safety_answers": ALL_NO}), cfg())
    return out


# ---- when it runs ----------------------------------------------------------------------------------


async def test_starting_triage_never_waits_for_the_model_but_starts_it_in_the_background():
    tools, assessor = FakeTriageTools([cand("s1")]), FakeAssessor()
    out = await graph(tools, assessor).ainvoke({"auth": ASHA, "intake_text": "knee pain for a week"}, cfg())
    assert out["__interrupt__"][0].value["type"] == "safety_check"
    assert assessor.calls == []  # the safety questions come back on rules alone
    assert assessor.prefetched == ["knee pain for a week"]  # ...while the check runs behind them


async def test_one_model_call_per_pass_after_the_safety_answers():
    tools, assessor = FakeTriageTools([cand("s1")]), FakeAssessor()
    await run(graph(tools, assessor), "knee pain for a week")
    assert assessor.calls == ["knee pain for a week"]


# ---- red flags: rules first, model second, and the model can only add ------------------------------


async def test_the_model_catches_an_emergency_the_rules_and_answers_missed():
    tools, assessor = FakeTriageTools([cand("s1")]), FakeAssessor(flags=["redflag_self_harm"])
    out = await run(graph(tools, assessor), "apni jaan lena chahta hoon")
    assert out["outcome"] == "emergency"
    assert tools.handoffs[0]["reason"] == "redflag_self_harm:model"
    assert tools.shortlist_calls == 0


async def test_when_the_rules_fire_the_model_is_never_asked_and_cannot_overrule():
    tools, assessor = FakeTriageTools([cand("s1")]), FakeAssessor(flags=[])
    out = await graph(tools, assessor).ainvoke(
        {"auth": ASHA, "intake_text": "crushing chest pain right now"}, cfg()
    )
    assert out["outcome"] == "emergency"
    assert assessor.calls == []


async def test_a_skipped_model_check_continues_exactly_like_rules_only():
    tools, assessor = FakeTriageTools([cand("s1")]), FakeAssessor(skipped="timeout")
    out = await run(graph(tools, assessor), "knee pain for a week")
    assert out["__interrupt__"][0].value["type"] == "pick_slot"
    assert out["model_skipped"] == "timeout"


# ---- specialty: rules first; the model's guess only when they're unsure, above the threshold -------


async def test_rules_decide_when_they_are_sure_even_if_the_model_disagrees():
    guess = SpecialtyGuess("Rheumatology", None, 0.9)
    tools, assessor = FakeTriageTools([cand("s1")]), FakeAssessor(guess=guess)
    out = await run(graph(tools, assessor), "knee pain for a week")
    assert out["specialty"] == "Orthopaedics" and out["specialty_rule_id"] != "model"


async def test_a_confident_model_guess_routes_when_the_rules_are_unsure():
    guess = SpecialtyGuess("Endocrinology", "General Medicine", 0.82)
    tools, assessor = FakeTriageTools([cand("s1")]), FakeAssessor(guess=guess)
    out = await run(graph(tools, assessor), "always thirsty and getting up to pee every night")
    assert out["__interrupt__"][0].value["type"] == "pick_slot"
    assert out["specialty"] == "Endocrinology" and out["alternative_specialty"] == "General Medicine"
    assert tools.specialties == ["Endocrinology"]  # the alternative is shown, never booked


async def test_a_low_confidence_or_missing_guess_asks_the_patient_instead():
    for guess in (SpecialtyGuess("Endocrinology", None, 0.4), None):
        tools, assessor = FakeTriageTools([cand("s1")]), FakeAssessor(guess=guess)
        out = await run(graph(tools, assessor), "I just don't feel right")
        assert out["__interrupt__"][0].value["type"] == "clarify"
        assert tools.shortlist_calls == 0


# ---- the model adapter: anything it can't stand behind becomes "nothing to add" ---------------------


def chat(**structured) -> EgressChatClient:
    return EgressChatClient(FakeChatModel(structured=structured))


async def test_the_adapter_maps_flags_and_rejects_specialties_we_do_not_book_into():
    result = await ModelAssessor(
        chat(flags=["stroke", "breathing"], specialty="Homeopathy", confidence=0.99)
    ).assess("x")
    assert result.red_flags == ["redflag_breathing", "redflag_stroke"]
    assert result.specialty is None


async def test_the_adapter_normalises_names_and_drops_a_duplicate_alternative():
    result = await ModelAssessor(
        chat(flags=[], specialty="dermatology", alternative="Dermatology", confidence=0.9)
    ).assess("itchy patches")
    assert result.specialty == SpecialtyGuess("Dermatology", None, 0.9)


async def test_a_failing_model_adds_nothing():
    class Broken:
        async def ask_structured(self, request, schema):
            raise RuntimeError("down")

    result = await ModelAssessor(Broken()).assess("anything")  # type: ignore[arg-type]
    assert result == Assessment([], None, skipped="unavailable")


async def test_a_slow_model_is_skipped_at_the_deadline():
    class Slow:
        async def ask_structured(self, request, schema):
            await asyncio.sleep(10)

    result = await ModelAssessor(Slow(), deadline_seconds=0.05).assess("anything")  # type: ignore[arg-type]
    assert result == Assessment([], None, skipped="timeout")


def test_the_specialty_list_matches_the_network():
    assert set(SPECIALTIES) == {getattr(s, "name", s) for s in NETWORK_SPECIALTIES}


# ---- prefetch: the model runs while the patient answers, and is metered by whoever uses it ----------


class CountingChat:
    def __init__(self) -> None:
        self.calls = 0

    async def ask_structured(self, request, schema):
        from services.platform.tracing import record_model_call

        self.calls += 1
        record_model_call("gemini:flash", started=0.0, tokens_in=100, tokens_out=20, estimated=False)
        return schema(flags=[], specialty="Dermatology", confidence=0.9)


async def test_a_prefetched_check_is_used_once_and_metered_by_the_run_that_uses_it():
    from services.platform.tracing import MemorySpanSink, Prices, trace_run

    chat = CountingChat()
    assessor = ModelAssessor(chat)  # type: ignore[arg-type]
    start_sink, resume_sink = MemorySpanSink(), MemorySpanSink()
    prices = Prices({"flash": {"in": 1.0, "out": 1.0}})
    async with trace_run("triage", "start", start_sink, prices):
        assessor.prefetch("run-1", "itchy rash")
        await asyncio.sleep(0)  # the background call runs while the patient answers
    async with trace_run("triage", "resume", resume_sink, prices):
        result = await assessor.assess("itchy rash", key="run-1")
    assert chat.calls == 1 and result.specialty is not None
    assert [s.kind for s in start_sink.spans] == ["node"]  # only the run span: no orphaned model call
    [model] = [s for s in resume_sink.spans if s.kind == "model"]
    assert model.trace_id == "resume" and model.cost == round(120 / 1_000_000, 6)


async def test_new_text_after_a_clarification_gets_a_fresh_check():
    chat = CountingChat()
    assessor = ModelAssessor(chat)  # type: ignore[arg-type]
    assessor.prefetch("run-1", "not feeling right")
    await assessor.assess("not feeling right. itchy rash on my arms", key="run-1")
    assert chat.calls == 2
