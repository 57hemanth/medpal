"""In-boundary tracing: node and model spans, cost, no content, never breaks the request."""

from dataclasses import astuple
from datetime import date

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from services.agent.triage.graph import build_triage_graph
from services.platform.egress.client import EgressChatClient, ModelRequest
from services.platform.egress.providers import FakeChatModel
from services.platform.tracing import RUN_SPAN, MemorySpanSink, Prices, trace_run
from tests.unit.test_triage_graph import ASHA, FakeTriageTools, cand


async def test_every_graph_node_and_the_run_get_spans():
    sink = MemorySpanSink()
    graph = build_triage_graph(FakeTriageTools([cand("s1")])).compile(checkpointer=InMemorySaver())
    async with trace_run("triage", "thread-1", sink) as callbacks:
        await graph.ainvoke(
            {"auth": ASHA, "intake_text": "crushing chest pain"},
            {"configurable": {"thread_id": "thread-1"}, "callbacks": callbacks},
        )
    names = [s.name for s in sink.spans]
    assert {"intake", "red_flag_rules", "emergency_handoff"} <= set(names)
    assert names[-1] == RUN_SPAN
    assert all(s.trace_id == "thread-1" and s.workflow == "triage" and s.duration_ms >= 0 for s in sink.spans)


async def test_model_calls_are_metered_and_priced_with_the_list_date():
    sink = MemorySpanSink()
    prices = Prices({"FakeChatModel": {"in": 1.0, "out": 2.0}}, date(2026, 11, 3))
    async with trace_run("records", "r-1", sink, prices):
        await EgressChatClient(FakeChatModel(response="LDL is 162")).ask(
            ModelRequest(system="answer", user="What was my LDL? Patient Asha Verma", purpose="t")
        )
    [model_span] = [s for s in sink.spans if s.kind == "model"]
    assert model_span.tokens_in and model_span.tokens_out and model_span.tokens_estimated
    assert model_span.cost is not None and model_span.price_list_date == date(2026, 11, 3)


async def test_unpriced_models_cost_null_not_zero():
    sink = MemorySpanSink()
    async with trace_run("records", "r-2", sink):
        await EgressChatClient(FakeChatModel()).ask(ModelRequest(system="s", user="u", purpose="t"))
    [model_span] = [s for s in sink.spans if s.kind == "model"]
    assert model_span.cost is None


async def test_spans_never_contain_prompt_or_response_text():
    sink = MemorySpanSink()
    async with trace_run("records", "r-3", sink):
        await EgressChatClient(FakeChatModel(response="Your HbA1c is 6.8")).ask(
            ModelRequest(system="s", user="Patient Asha Verma, HbA1c question", purpose="t")
        )
    stored = " ".join(str(v) for s in sink.spans for v in astuple(s))
    assert "Asha" not in stored and "HbA1c" not in stored


class _BrokenSink:
    async def write(self, spans):
        raise ConnectionError("trace store down")


async def test_a_failing_trace_store_never_fails_the_request():
    async with trace_run("records", "r-4", _BrokenSink()):
        out = await EgressChatClient(FakeChatModel(response="ok")).ask(
            ModelRequest(system="s", user="u", purpose="t")
        )
    assert out.text == "ok"


async def test_errors_are_traced_with_the_exception_type_only():
    sink = MemorySpanSink()
    with pytest.raises(RuntimeError):
        async with trace_run("triage", "t-err", sink):
            raise RuntimeError("secret patient detail in a message")
    [run] = sink.spans
    assert run.status == "error" and run.error_type == "RuntimeError"
    assert "secret" not in " ".join(str(v) for v in astuple(run))
