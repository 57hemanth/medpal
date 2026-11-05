"""Email settings for patients, the address-confirmation link, and the record of messages sent."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from services.api.deps import auth_ctx
from services.notifications import service as notifications
from services.platform.auth import AuthContext
from services.platform.config import get_settings

router = APIRouter(prefix="/api", tags=["messages"])
Auth = Annotated[AuthContext, Depends(auth_ctx)]


class ContactIn(BaseModel):
    email: str | None = Field(default=None, max_length=254)
    email_notifications: bool = True


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/me/contact")
async def contact(request: Request, auth: Auth) -> dict[str, Any]:
    try:
        return await notifications.get_contact(request.app.state.app_pool, auth)
    except PermissionError as exc:
        raise _http(exc) from exc


@router.put("/me/contact")
async def update_contact(body: ContactIn, request: Request, auth: Auth) -> dict[str, Any]:
    try:
        return await notifications.update_contact(
            request.app.state.app_pool,
            auth,
            request.app.state.email_sender,
            get_settings(),
            email=body.email,
            email_notifications=body.email_notifications,
        )
    except (PermissionError, notifications.ContactError) as exc:
        raise _http(exc) from exc


@router.post("/me/contact/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend(request: Request, auth: Auth) -> dict[str, bool]:
    try:
        await notifications.send_verification(
            request.app.state.app_pool, auth, request.app.state.email_sender, get_settings()
        )
    except (PermissionError, notifications.ContactError) as exc:
        raise _http(exc) from exc
    return {"sent": True}


@router.get("/me/email/verify", include_in_schema=False)
async def verify(token: str, request: Request) -> RedirectResponse:
    """Opened from the email, possibly on another device: needs no session, only the signed link."""
    ok = await notifications.confirm_email(request.app.state.app_pool, token[:2000], get_settings())
    return RedirectResponse(f"/settings?email={'confirmed' if ok else 'link-expired'}", status_code=303)


@router.get("/messages")
async def messages(request: Request, auth: Auth, limit: int = 200) -> list[dict[str, Any]]:
    return await notifications.list_messages(request.app.state.app_pool, auth, limit=limit)
