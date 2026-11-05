"""In-boundary tracing and cost metering.

    async with trace_run("triage", thread_id, sink) as callbacks:
        out = await graph.ainvoke(payload, {"configurable": {...}, "callbacks": callbacks})

* Graph nodes are timed by a LangChain callback (no change to graph code).
* Model calls are recorded by the egress client: model id, tokens, cost. Tokens come from the provider's
  usage report when available, otherwise they are estimated (~4 characters per token) and flagged.
* Spans hold metadata only (names, timings, counts), never prompt, response or document text.
* Cost uses configured prices with their price-list date; an unpriced model costs NULL, never zero.
* Tracing must never break a request: write failures are logged and dropped.
"""

import contextlib
import logging
import time
from collections.abc import AsyncIterator, Mapping
from contextvars import ContextVar
from dataclasses import astuple, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)

RUN_SPAN = "__run__"


@dataclass(frozen=True)
class Span:
    trace_id: str
    workflow: str
    kind: str  # node | model | tool
    name: str
    started_at: datetime
    duration_ms: float
    status: str = "ok"
    error_type: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_estimated: bool = False
    cost: float | None = None
    price_list_date: date | None = None


class SpanSink(Protocol):
    async def write(self, spans: list[Span]) -> None: ...


class PostgresSpanSink:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def write(self, spans: list[Span]) -> None:
        if not spans:
            return
        async with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO trace_span (trace_id, workflow, kind, name, started_at, duration_ms, status,"
                " error_type, tokens_in, tokens_out, tokens_estimated, cost, price_list_date)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [astuple(s) for s in spans],
            )


class MemorySpanSink:
    def __init__(self) -> None:
        self.spans: list[Span] = []

    async def write(self, spans: list[Span]) -> None:
        self.spans.extend(spans)


@dataclass
class Prices:
    """Per-million-token prices by model id, with the date the price list was read."""

    per_million: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    list_date: date | None = None

    def cost(self, model: str, tokens_in: int, tokens_out: int) -> float | None:
        price = self.per_million.get(model) or self.per_million.get(model.split(":", 1)[-1])
        if not price:
            return None
        return round((tokens_in * price["in"] + tokens_out * price["out"]) / 1_000_000, 6)


@dataclass
class _Run:
    trace_id: str
    workflow: str
    prices: Prices
    spans: list[Span] = field(default_factory=list)


_current: ContextVar[_Run | None] = ContextVar("medpal_trace_run", default=None)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def record_model_call(
    model: str,
    *,
    started: float,
    status: str = "ok",
    error_type: str | None = None,
    tokens_in: int,
    tokens_out: int,
    estimated: bool,
) -> None:
    """Called by the egress client. A no-op outside a traced run."""
    run = _current.get()
    if run is None:
        return
    run.spans.append(
        Span(
            run.trace_id,
            run.workflow,
            "model",
            model,
            datetime.now(UTC),
            (time.perf_counter() - started) * 1000,
            status,
            error_type,
            tokens_in,
            tokens_out,
            estimated,
            run.prices.cost(model, tokens_in, tokens_out) if status == "ok" else None,
            run.prices.list_date,
        )
    )


class _NodeTimer(AsyncCallbackHandler):
    """Times every LangGraph node of the run it is attached to."""

    def __init__(self, run: _Run) -> None:
        self._run = run
        self._open: dict[UUID, tuple[str, float, datetime]] = {}

    async def on_chain_start(
        self, serialized: Any, inputs: Any, *, run_id: UUID, metadata: Any = None, **_: Any
    ) -> None:
        node = (metadata or {}).get("langgraph_node")
        if node:
            self._open[run_id] = (str(node), time.perf_counter(), datetime.now(UTC))

    async def _close(self, run_id: UUID, status: str, error: BaseException | None = None) -> None:
        opened = self._open.pop(run_id, None)
        if opened is None:
            return
        name, started, at = opened
        self._run.spans.append(
            Span(
                self._run.trace_id,
                self._run.workflow,
                "node",
                name,
                at,
                (time.perf_counter() - started) * 1000,
                status,
                type(error).__name__ if error else None,
            )
        )

    async def on_chain_end(self, outputs: Any, *, run_id: UUID, **_: Any) -> None:
        await self._close(run_id, "ok")

    async def on_chain_error(self, error: BaseException, *, run_id: UUID, **_: Any) -> None:
        await self._close(run_id, "error", error)


@contextlib.asynccontextmanager
async def trace_run(
    workflow: str, trace_id: str, sink: SpanSink | None, prices: Prices | None = None
) -> AsyncIterator[list[AsyncCallbackHandler]]:
    """Trace one graph invocation. Yields the callbacks to pass in the run config."""
    run = _Run(trace_id, workflow, prices or Prices())
    token = _current.set(run)
    started, at = time.perf_counter(), datetime.now(UTC)
    status, error_type = "ok", None
    try:
        yield [_NodeTimer(run)]
    except BaseException as exc:
        status, error_type = "error", type(exc).__name__
        raise
    finally:
        _current.reset(token)
        run.spans.append(
            Span(
                trace_id,
                workflow,
                "node",
                RUN_SPAN,
                at,
                (time.perf_counter() - started) * 1000,
                status,
                error_type,
            )
        )
        if sink is not None:
            try:
                await sink.write(run.spans)
            except Exception as exc:  # noqa: BLE001 - tracing must never fail the request
                log.warning("dropping %d trace spans: %s", len(run.spans), type(exc).__name__)
