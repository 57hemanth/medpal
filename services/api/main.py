"""FastAPI app factory. `uvicorn services.api.main:app` runs it against Postgres."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from services.agent.scribe.graph import build_scribe_graph
from services.agent.scribe.tools import PgScribeTools
from services.agent.triage.graph import build_triage_graph
from services.agent.triage.tools import PgTriageTools
from services.api.routers import consent, me, ops, records, scribe, triage
from services.mcp_server.server import build_mcp_server
from services.platform.config import get_settings
from services.platform.db import app_pool, checkpoint_pool
from services.platform.egress import EgressChatClient, build_model_routes
from services.platform.tracing import PostgresSpanSink, Prices
from services.records.storage import build_object_store
from services.scribe.speech import LocalSpeechTranscriber

STATIC_DIR = next((path for path in (Path("static"), Path("web/dist")) if path.exists()), None)


@asynccontextmanager
async def _postgres_lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    pool, cp_pool = app_pool(settings), checkpoint_pool(settings)
    await pool.open()
    await cp_pool.open()
    try:
        saver = AsyncPostgresSaver(cp_pool)  # type: ignore[arg-type]
        await saver.setup()  # idempotent; creates checkpoint tables in the langgraph schema
        app.state.app_pool = pool
        app.state.trace_sink = PostgresSpanSink(pool)
        app.state.prices = Prices(settings.model_prices, settings.price_list_date)
        if settings.ingest_mode == "queue":
            app.state.ingest_queue = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        app.state.object_store = build_object_store(settings)
        app.state.speech_transcriber = LocalSpeechTranscriber(settings.speech_model_path)
        routes = build_model_routes(settings)
        app.state.chat_client = EgressChatClient(routes["large"], routes=routes)
        app.state.triage_graph = build_triage_graph(PgTriageTools(pool)).compile(checkpointer=saver)
        app.state.scribe_graph = build_scribe_graph(PgScribeTools(pool, app.state.chat_client)).compile(
            checkpointer=saver
        )
        async with app.state.mcp_server.session_manager.run():
            yield
    finally:
        queue = getattr(app.state, "ingest_queue", None)
        if queue is not None:
            await queue.aclose()
        await pool.close()
        await cp_pool.close()


def create_app(*, triage_graph: Any | None = None) -> FastAPI:
    """Pass a compiled graph to skip Postgres (unit tests); otherwise the lifespan wires it up."""

    @asynccontextmanager
    async def _injected_lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.triage_graph = triage_graph
        yield

    app = FastAPI(
        title="MedPal",
        version="0.1.0",
        lifespan=_injected_lifespan if triage_graph is not None else _postgres_lifespan,
    )
    # MCP tool server (scheduling and stock) over streamable HTTP, sharing the API's pool and identity rules.
    app.state.mcp_server = build_mcp_server(lambda: app.state.app_pool)
    app.mount("/mcp", app.state.mcp_server.streamable_http_app(streamable_http_path="/", host="0.0.0.0"))  # noqa: S104
    app.include_router(triage.router)
    app.include_router(me.router)
    app.include_router(records.router)
    app.include_router(consent.router)
    app.include_router(scribe.router)
    app.include_router(ops.router)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    if STATIC_DIR is not None:
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str, request: Request) -> HTMLResponse:
            if path.startswith(("api/", "triage/", "mcp", "docs", "openapi.json", "healthz")) or "." in path:
                raise HTTPException(status_code=404)
            if "text/html" not in request.headers.get("accept", ""):
                raise HTTPException(status_code=404)
            return HTMLResponse((STATIC_DIR / "index.html").read_text())

    return app


app = create_app()
