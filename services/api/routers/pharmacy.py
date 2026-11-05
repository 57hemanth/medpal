"""Pharmacy workspace, plus what patients see of their prescriptions and notifications."""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status

from services.api.deps import auth_ctx
from services.pharmacy import service as pharmacy
from services.platform.auth import AuthContext

router = APIRouter(prefix="/api", tags=["pharmacy"])
Auth = Annotated[AuthContext, Depends(auth_ctx)]


def _forbidden(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))


@router.get("/pharmacy/me")
async def pharmacy_me(request: Request, auth: Auth) -> dict[str, Any]:
    try:
        return await pharmacy.my_clinic(request.app.state.app_pool, auth)
    except pharmacy.NotAllowed as exc:
        raise _forbidden(exc) from exc


@router.get("/pharmacy/medicines")
async def medicines(request: Request, auth: Auth, q: str = "", limit: int = 100) -> list[dict[str, Any]]:
    try:
        return await pharmacy.catalogue(request.app.state.app_pool, auth, query=q[:100], limit=limit)
    except pharmacy.NotAllowed as exc:
        raise _forbidden(exc) from exc


@router.get("/pharmacy/stock")
async def stock(request: Request, auth: Auth) -> list[dict[str, Any]]:
    try:
        return await pharmacy.clinic_stock(request.app.state.app_pool, auth)
    except pharmacy.NotAllowed as exc:
        raise _forbidden(exc) from exc


@router.get("/pharmacy/queue")
async def queue(
    request: Request,
    auth: Auth,
    status_filter: Literal["reserved", "dispensed", "released", "all"] = "reserved",
) -> list[dict[str, Any]]:
    try:
        return await pharmacy.dispensing_queue(request.app.state.app_pool, auth, status=status_filter)
    except pharmacy.NotAllowed as exc:
        raise _forbidden(exc) from exc


@router.post("/pharmacy/queue/{reservation_id}/{action}")
async def close_reservation(
    reservation_id: str, action: Literal["dispense", "release"], request: Request, auth: Auth
) -> dict[str, str]:
    try:
        uuid.UUID(reservation_id)
        handler = pharmacy.dispense if action == "dispense" else pharmacy.release
        await handler(request.app.state.app_pool, auth, reservation_id=reservation_id)
    except pharmacy.NotAllowed as exc:
        raise _forbidden(exc) from exc
    except (ValueError, LookupError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no reserved prescription with that id") from exc
    return {"reservation_id": reservation_id, "status": "dispensed" if action == "dispense" else "released"}


@router.get("/prescriptions")
async def prescriptions(request: Request, auth: Auth) -> list[dict[str, Any]]:
    if auth["role"] not in ("patient", "caregiver"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "prescriptions here are a patient's own view")
    return await pharmacy.my_prescriptions(request.app.state.app_pool, auth)


@router.get("/notifications")
async def notifications(request: Request, auth: Auth) -> list[dict[str, Any]]:
    if auth["role"] not in ("patient", "caregiver"):
        return []
    return await pharmacy.notifications(request.app.state.app_pool, auth)


@router.post("/notifications/{notification_id}/read")
async def read_notification(notification_id: str, request: Request, auth: Auth) -> dict[str, str]:
    try:
        uuid.UUID(notification_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found") from exc
    await pharmacy.mark_read(request.app.state.app_pool, auth, notification_id=notification_id)
    return {"notification_id": notification_id}
