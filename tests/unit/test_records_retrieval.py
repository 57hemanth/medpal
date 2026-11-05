import pytest

from services.records.embedding import DIMENSIONS, embed_text, pgvector_literal
from services.records.qa import needs_doctor_review


def test_local_embedding_shape_is_fixed_for_pgvector_schema():
    vector = embed_text("LDL 162 mg/dL")

    assert len(vector) == DIMENSIONS
    assert pgvector_literal(vector).startswith("[")


def test_diagnosis_and_dose_questions_need_doctor_review():
    assert needs_doctor_review("Can you diagnose this?")
    assert needs_doctor_review("Should I increase medicine dose?")
    assert not needs_doctor_review("What was my LDL in the report?")


def test_lexical_query_is_an_or_of_meaningful_words_plus_clinical_terms():
    from services.records.retrieval import lexical_query

    assert lexical_query("mera sugar test ka result kya tha?") == "sugar | glucose | hba1c | diabetes"
    assert "ldl" in lexical_query("What was my LDL?").split(" | ")


def test_lexical_query_cannot_inject_tsquery_syntax():
    from services.records.retrieval import lexical_query

    assert lexical_query("it's & | ! (x) <-> :*") == ""
    assert set(lexical_query("drop table; -- x'y")) <= set("abcdefghijklmnopqrstuvwxyz0123456789 |")


@pytest.mark.parametrize(
    ("tier", "expected"), [("small", "needs_doctor"), ("large", "insufficient_evidence")]
)
async def test_records_answers_use_the_configured_model_tier(monkeypatch, tier, expected):
    from services.platform.egress.client import EgressChatClient
    from services.platform.egress.providers import FakeChatModel
    from services.records import qa
    from services.records.retrieval import RetrievedChunk

    async def one_chunk(*_args, **_kwargs):
        return [RetrievedChunk("c1", "d1", "p1", 1, 0, "LDL 162 mg/dL", 1.0)]

    monkeypatch.setattr(qa, "retrieve", one_chunk)
    small = FakeChatModel(structured={"answer": "", "citation_ids": [], "needs_doctor": True})
    large = FakeChatModel(structured={"answer": "x", "citation_ids": [], "needs_doctor": False})
    chat = EgressChatClient(large, routes={"small": small, "large": large})
    auth = {"user_id": "u", "role": "patient", "acting_for_patient_id": "p1"}
    result = await qa.answer_question(None, chat, auth, question="What was my LDL?", tier=tier)  # type: ignore[arg-type]
    assert result.status == expected
