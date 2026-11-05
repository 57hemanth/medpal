"""Hybrid records retrieval scoped by Postgres RLS."""

import re
from dataclasses import dataclass
from typing import Any, cast

from psycopg_pool import AsyncConnectionPool

from services.platform.auth import AuthContext
from services.platform.db import scoped

from .embedding import embed_text, pgvector_literal


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    patient_id: str
    page: int
    ordinal: int
    text: str
    score: float


# Words that carry no meaning for matching a report (English and romanised Hindi question fillers).
_STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "my",
        "me",
        "i",
        "is",
        "was",
        "were",
        "are",
        "am",
        "be",
        "been",
        "what",
        "whats",
        "when",
        "which",
        "who",
        "how",
        "much",
        "many",
        "do",
        "does",
        "did",
        "of",
        "in",
        "on",
        "at",
        "for",
        "to",
        "from",
        "and",
        "or",
        "with",
        "about",
        "tell",
        "show",
        "give",
        "please",
        "can",
        "could",
        "you",
        "your",
        "this",
        "that",
        "it",
        "last",
        "latest",
        "recent",
        "report",
        "reports",
        "result",
        "results",
        "test",
        "tests",
        "value",
        "level",
        "levels",
        "mera",
        "meri",
        "mere",
        "mujhe",
        "kya",
        "tha",
        "thi",
        "the",
        "hai",
        "hain",
        "ka",
        "ki",
        "ke",
        "ko",
        "se",
        "mein",
        "me",
        "aur",
        "batao",
        "bataiye",
        "kitna",
        "kitni",
        "kab",
    ]
)
# How people ask vs how reports are written. Deterministic, in-boundary, and easy to review.
_LAY_TERMS: dict[str, tuple[str, ...]] = {
    "sugar": ("glucose", "hba1c", "diabetes"),
    "diabetes": ("glucose", "hba1c"),
    "cholesterol": ("ldl", "hdl", "lipid", "triglycerides"),
    "fat": ("lipid", "triglycerides"),
    "thyroid": ("tsh", "t3", "t4"),
    "blood": ("haemoglobin", "hemoglobin", "cbc"),
    "khoon": ("haemoglobin", "hemoglobin", "cbc"),
    "kidney": ("creatinine", "urea", "egfr"),
    "liver": ("alt", "ast", "sgpt", "sgot", "bilirubin"),
    "iron": ("ferritin", "haemoglobin"),
    "bp": ("pressure",),
    "heart": ("ecg", "cardiac"),
}


def lexical_query(question: str) -> str:
    """An OR full-text query of the question's meaningful words plus clinical synonyms.

    Tokens are reduced to [a-z0-9] before they reach to_tsquery, so nothing in the question can alter the
    query's structure. Returns "" when nothing meaningful is left (the vector score still ranks).
    """
    words = [w for w in re.findall(r"[a-z0-9]+", question.lower()) if w not in _STOP and len(w) > 1]
    terms: list[str] = []
    for word in words:
        for term in (word, *_LAY_TERMS.get(word, ())):
            if term not in terms:
                terms.append(term)
    return " | ".join(terms[:24])


async def retrieve(
    pool: AsyncConnectionPool,
    auth: AuthContext,
    *,
    question: str,
    patient_id: str | None = None,
    limit: int = 5,
) -> list[RetrievedChunk]:
    """Chunks the caller may read (RLS) that match the question.

    `patient_id` narrows to ONE patient on top of RLS: a caregiver with consent from two people must
    never get both people's reports mixed into a single answer. RLS still decides whether the caller
    may see that patient at all.
    """
    query_embedding = pgvector_literal(embed_text(question))
    async with scoped(pool, auth) as conn:
        rows = await (
            await conn.execute(
                """
                WITH q AS (
                    SELECT to_tsquery('simple', %s) AS tsq, %s::vector AS embedding
                )
                SELECT c.chunk_id::text, c.doc_id::text, c.patient_id::text, c.page, c.ordinal, c.text,
                       (
                         ts_rank_cd(c.tsv, q.tsq)
                         + CASE WHEN c.embedding IS NULL THEN 0 ELSE 1 - (c.embedding <=> q.embedding) END
                       ) AS score
                  FROM doc_chunk c, q
                 WHERE (c.tsv @@ q.tsq OR c.embedding IS NOT NULL)
                   AND (%s::uuid IS NULL OR c.patient_id = %s::uuid)
                 ORDER BY score DESC, c.page, c.ordinal
                 LIMIT %s
                """,
                (lexical_query(question), query_embedding, patient_id, patient_id, limit),
            )
        ).fetchall()
    return [RetrievedChunk(**cast(dict[str, Any], row)) for row in rows]
