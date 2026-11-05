"""Request-side tracing helper: every graph run and model-backed request is traced in-boundary."""

from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import Request

from services.platform.tracing import trace_run


def traced(request: Request, workflow: str, trace_id: str) -> AbstractAsyncContextManager[list[Any]]:
    state = request.app.state
    return trace_run(workflow, trace_id, getattr(state, "trace_sink", None), getattr(state, "prices", None))
