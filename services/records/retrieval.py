"""Hybrid records retrieval scoped by Postgres RLS."""

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


async def retrieve(
    pool: AsyncConnectionPool, auth: AuthContext, *, question: str, limit: int = 5
) -> list[RetrievedChunk]:
    query_embedding = pgvector_literal(embed_text(question))
    async with scoped(pool, auth) as conn:
        rows = await (
            await conn.execute(
                """
                WITH q AS (
                    SELECT plainto_tsquery('simple', %s) AS tsq, %s::vector AS embedding
                )
                SELECT c.chunk_id::text, c.doc_id::text, c.patient_id::text, c.page, c.ordinal, c.text,
                       (
                         ts_rank_cd(c.tsv, q.tsq)
                         + CASE WHEN c.embedding IS NULL THEN 0 ELSE 1 - (c.embedding <=> q.embedding) END
                       ) AS score
                  FROM doc_chunk c, q
                 WHERE c.tsv @@ q.tsq OR c.embedding IS NOT NULL
                 ORDER BY score DESC, c.page, c.ordinal
                 LIMIT %s
                """,
                (question, query_embedding, limit),
            )
        ).fetchall()
    return [RetrievedChunk(**cast(dict[str, Any], row)) for row in rows]
