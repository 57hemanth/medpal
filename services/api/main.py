"""FastAPI app factory. `uvicorn services.api.main:app` runs it against Postgres."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from services.agent.triage.graph import build_triage_graph
from services.agent.triage.tools import PgTriageTools
from services.api.routers import triage
from services.platform.config import get_settings
from services.platform.db import app_pool, checkpoint_pool


@asynccontextmanager
async def _postgres_lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    pool, cp_pool = app_pool(settings), checkpoint_pool(settings)
    await pool.open()
    await cp_pool.open()
    try:
        saver = AsyncPostgresSaver(cp_pool)  # type: ignore[arg-type]
        await saver.setup()  # idempotent; creates checkpoint tables in the langgraph schema
        app.state.triage_graph = build_triage_graph(PgTriageTools(pool)).compile(checkpointer=saver)
        yield
    finally:
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
    app.include_router(triage.router)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
