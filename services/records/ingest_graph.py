"""Records ingest as a graph: one task per page, in parallel under a bounded pool.

    load ──Send(page 1..n)──► process_page (text layer, else local OCR → chunk → embed)  ×n, parallel
                                        │  results gathered by an add-reducer
                                        ▼
                                     write (all chunks in one transaction) → ready | needs_review

Runs on the queue worker. No checkpointer: there is no human step, and the job row in Postgres is the
durable state (a crashed run is simply retried; content-addressed uploads make that idempotent).
"""

import asyncio
import operator
from typing import Annotated, Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from psycopg_pool import AsyncConnectionPool

from services.platform.db import scoped_system

from .embedding import embed_text, pgvector_literal
from .ingest import MAX_TEXT_CHARS, chunk_text, extract_page, page_count
from .storage import ObjectStore

DEFAULT_MAX_CONCURRENCY = 4


class PageResult(TypedDict):
    page: int
    chunks: list[tuple[str, str]]  # (text, pgvector literal)
    error: str | None


class IngestState(TypedDict, total=False):
    doc_id: str
    patient_id: str
    content: bytes
    content_type: str
    pages: int
    results: Annotated[list[PageResult], operator.add]
    status: str
    error: str | None


class PageTask(TypedDict):
    content: bytes
    content_type: str
    page: int


def build_ingest_graph(pool: AsyncConnectionPool, store: ObjectStore) -> Any:
    async def load(state: IngestState) -> IngestState:
        async with scoped_system(pool) as conn:
            doc = cast(
                dict[str, Any],
                await (
                    await conn.execute(
                        "SELECT doc_id::text, patient_id::text, uri FROM document WHERE doc_id = %s",
                        (state["doc_id"],),
                    )
                ).fetchone(),
            )
            await conn.execute(
                "UPDATE ingest_job SET status = 'running', updated_at = now() WHERE doc_id = %s",
                (state["doc_id"],),
            )
        content = await store.get(doc["uri"])
        content_type = "application/pdf" if content.startswith(b"%PDF") else "text/plain"
        pages = await asyncio.to_thread(page_count, content, content_type)
        return {
            "patient_id": doc["patient_id"],
            "content": content,
            "content_type": content_type,
            "pages": pages,
        }

    def fan_out(state: IngestState) -> list[Send] | str:
        if not state["pages"]:
            return "write"
        return [
            Send(
                "process_page", PageTask(content=state["content"], content_type=state["content_type"], page=n)
            )
            for n in range(1, state["pages"] + 1)
        ]

    async def process_page(state: PageTask) -> IngestState:
        text = await asyncio.to_thread(extract_page, state["content"], state["content_type"], state["page"])
        if text is None or not text.strip():
            return {"results": [PageResult(page=state["page"], chunks=[], error="page_unreadable")]}
        chunks = chunk_text(text)
        vectors = await asyncio.to_thread(lambda: [pgvector_literal(embed_text(c)) for c in chunks])
        return {
            "results": [
                PageResult(page=state["page"], chunks=list(zip(chunks, vectors, strict=True)), error=None)
            ]
        }

    async def write(state: IngestState) -> IngestState:
        results = sorted(state.get("results", []), key=lambda r: r["page"])
        error = None
        if not state["pages"]:
            error = "invalid_document"
        elif any(r["error"] for r in results):
            error = "ocr_unavailable_or_unreadable_page"
        elif sum(len(text) for r in results for text, _ in r["chunks"]) > MAX_TEXT_CHARS:
            error = "extracted_text_too_large"
        async with scoped_system(pool) as conn:
            if error:
                await conn.execute(
                    "UPDATE ingest_job SET status = 'needs_review', error = %s, updated_at = now()"
                    " WHERE doc_id = %s",
                    (error, state["doc_id"]),
                )
                return {"status": "needs_review", "error": error}
            ordinal = 0
            for result in results:
                for text, vector in result["chunks"]:
                    await conn.execute(
                        "INSERT INTO doc_chunk (doc_id, patient_id, page, ordinal, text, embedding)"
                        " VALUES (%s, %s, %s, %s, %s, %s::vector)"
                        " ON CONFLICT (doc_id, page, ordinal) DO NOTHING",
                        (state["doc_id"], state["patient_id"], result["page"], ordinal, text, vector),
                    )
                    ordinal += 1
            await conn.execute(
                "UPDATE document SET phi_status = 'tagged' WHERE doc_id = %s", (state["doc_id"],)
            )
            await conn.execute(
                "UPDATE ingest_job SET status = 'ready', error = NULL, updated_at = now() WHERE doc_id = %s",
                (state["doc_id"],),
            )
        return {"status": "ready", "error": None}

    g = StateGraph(IngestState)
    g.add_node("load", load)
    g.add_node("process_page", process_page, input_schema=PageTask)
    g.add_node("write", write)
    g.add_edge(START, "load")
    g.add_conditional_edges("load", fan_out, ["process_page", "write"])
    g.add_edge("process_page", "write")
    g.add_edge("write", END)
    return g.compile()


async def run_ingest(
    pool: AsyncConnectionPool,
    store: ObjectStore,
    *,
    doc_id: str,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> str:
    out = await build_ingest_graph(pool, store).ainvoke(
        {"doc_id": doc_id}, {"max_concurrency": max_concurrency}
    )
    return str(out["status"])


def job_id(doc_id: str) -> str:
    """Queue job id for a document: duplicate enqueues of one document collapse into one job."""
    return f"ingest:{doc_id}"
