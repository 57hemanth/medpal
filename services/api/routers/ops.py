"""Appointment and front-desk APIs."""

import json
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from services.api.deps import auth_ctx
from services.platform.auth import AuthContext
from services.platform.db import scoped
from services.platform.metrics import collect
from services.scheduling.operations import (
    cancel_appointment,
    list_appointments,
    list_handoffs,
    update_handoff_status,
)

router = APIRouter(prefix="/api", tags=["operations"])

Auth = Annotated[AuthContext, Depends(auth_ctx)]


class HandoffStatusIn(BaseModel):
    status: Literal["open", "in_progress", "closed"]


@router.get("/appointments")
async def appointments(
    request: Request,
    auth: Auth,
    when: Literal["upcoming", "past", "all"] = "all",
    limit: int = 200,
) -> list[dict[str, Any]]:
    return await list_appointments(request.app.state.app_pool, auth, when=when, limit=limit)


@router.post("/appointments/{appt_id}/cancel")
async def cancel(appt_id: str, request: Request, auth: Auth) -> dict[str, Any]:
    try:
        return await cancel_appointment(request.app.state.app_pool, auth, appt_id=appt_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.get("/front-desk/handoffs")
async def handoffs(request: Request, auth: Auth) -> list[dict[str, Any]]:
    if auth["role"] != "desk":
        raise HTTPException(403, "front-desk queue requires desk role")
    return await list_handoffs(request.app.state.app_pool, auth)


@router.post("/front-desk/handoffs/{ticket_id}/status")
async def handoff_status(
    ticket_id: str, body: HandoffStatusIn, request: Request, auth: Auth
) -> dict[str, Any]:
    if auth["role"] != "desk":
        raise HTTPException(403, "front-desk queue requires desk role")
    try:
        return await update_handoff_status(
            request.app.state.app_pool, auth, ticket_id=ticket_id, status=body.status
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.get("/ops/metrics")
async def metrics(request: Request, auth: Auth, hours: int = 24) -> dict[str, Any]:
    """Latency percentiles, error rates, tokens and cost per run, from the in-boundary trace store."""
    if auth["role"] != "compliance":
        raise HTTPException(403, "operational metrics require the compliance role")
    async with scoped(request.app.state.app_pool, auth) as conn:
        return await collect(conn, hours=max(1, min(hours, 24 * 30)))


@router.get("/audit")
async def audit_log(
    request: Request,
    auth: Auth,
    resource: str | None = None,
    action: str | None = None,
    patient_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Recent audit events for the compliance console: who did what, to which record, why, under which
    trace. Row-level security already limits the table; this endpoint is compliance-only on top."""
    if auth["role"] != "compliance":
        raise HTTPException(403, "the audit log requires the compliance role")
    async with scoped(request.app.state.app_pool, auth) as conn:
        cur = await conn.execute(
            "SELECT e.event_id, e.at, e.actor_id::text, e.actor_role, e.action, e.resource, e.record_id,"
            " e.patient_id::text, p.name AS patient_name, e.purpose, e.trace_id"
            " FROM audit_event e LEFT JOIN patient p ON p.patient_id = e.patient_id"
            " WHERE (%(resource)s::text IS NULL OR e.resource = %(resource)s)"
            " AND (%(action)s::text IS NULL OR e.action = %(action)s)"
            " AND (%(patient)s::uuid IS NULL OR e.patient_id = %(patient)s::uuid)"
            " ORDER BY e.at DESC LIMIT %(limit)s",
            {
                "resource": resource,
                "action": action,
                "patient": patient_id,
                "limit": max(1, min(limit, 500)),
            },
        )
        return cast(list[dict[str, Any]], await cur.fetchall())


RUNS = Path(__file__).resolve().parents[3] / "evals" / "runs"


def _latest(pattern: str, exclude: str | None = None) -> tuple[str, dict[str, Any]] | None:
    files = sorted(p for p in RUNS.glob(pattern) if not (exclude and p.name.startswith(exclude)))
    if not files:
        return None
    return files[-1].name, json.loads(files[-1].read_text())


@router.get("/ops/quality")
async def quality(auth: Auth) -> dict[str, Any]:
    """The latest evaluation run (rules, gated) and live check (real model), as written by `make eval` and
    `make live-check`. Read from the run files; nothing here is recomputed or estimated."""
    if auth["role"] != "compliance":
        raise HTTPException(403, "quality results require the compliance role")
    evaluation = _latest("2*.json")
    live = _latest("live-*.json")
    return {
        "evaluation": {"file": evaluation[0], **evaluation[1]} if evaluation else None,
        "live": {"file": live[0], **live[1]} if live else None,
    }
