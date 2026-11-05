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
