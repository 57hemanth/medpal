"""Appointment and front-desk APIs."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from services.api.deps import auth_ctx
from services.platform.auth import AuthContext
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
async def appointments(request: Request, auth: Auth) -> list[dict[str, Any]]:
    return await list_appointments(request.app.state.app_pool, auth)


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
