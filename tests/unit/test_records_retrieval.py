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
