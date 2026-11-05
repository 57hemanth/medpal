"""Mobile sign-in: request a code, verify it, register a new patient, switch role, sign out."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from services.api.deps import auth_ctx
from services.platform import signin
from services.platform.auth import AuthContext
from services.platform.config import get_settings
from services.platform.db import scoped_system

router = APIRouter(prefix="/api", tags=["auth"])
Auth = Annotated[AuthContext, Depends(auth_ctx)]
SENDER = signin.LogSmsSender()


class PhoneIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)


class VerifyIn(PhoneIn):
    code: str = Field(min_length=4, max_length=8)


class RegisterIn(BaseModel):
    registration_token: str = Field(min_length=10, max_length=2000)
    name: str = Field(min_length=2, max_length=120)
    dob: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    city: str | None = Field(default=None, max_length=60)


class RoleIn(BaseModel):
    role: str


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


def _set_session(response: Response, auth: AuthContext) -> None:
    settings = get_settings()
    response.set_cookie(
        signin.COOKIE,
        signin.session_token(auth, settings),
        max_age=settings.session_hours * 3600,
        httponly=True,  # scripts can never read the session
        samesite="lax",  # not sent on cross-site posts
        secure=settings.env == "prod",
        path="/",
    )


async def _session_for(
    request: Request, response: Response, user_id: str, prefer: str | None = None
) -> dict[str, Any]:
    roles = await signin.roles_for(request.app.state.app_pool, user_id)
    if not roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has nothing to access yet")
    chosen = next((r for r in roles if r["role"] == prefer), roles[0])
    _set_session(response, chosen)
    return {"signed_in": True, "role": chosen["role"], "roles": [r["role"] for r in roles]}


@router.post("/auth/otp/start")
async def start(body: PhoneIn, request: Request) -> dict[str, Any]:
    settings = get_settings()
    try:
        phone = signin.normalize_phone(body.phone)
        dev_code = await signin.start(request.app.state.app_pool, phone, settings, SENDER)
    except signin.SignInError as exc:
        raise _bad(exc) from exc
    out: dict[str, Any] = {"sent": True, "phone": signin.mask_phone(phone)}
    if dev_code:
        out["dev_code"] = dev_code  # development only: no SMS gateway is configured
    return out


@router.post("/auth/otp/verify")
async def verify(body: VerifyIn, request: Request, response: Response) -> dict[str, Any]:
    try:
        result = await signin.verify(request.app.state.app_pool, body.phone, body.code, get_settings())
    except signin.SignInError as exc:
        raise _bad(exc) from exc
    if result.user_id and not result.registration_token:
        return await _session_for(request, response, result.user_id)
    out: dict[str, Any] = {"signed_in": False, "registration_token": result.registration_token}
    if result.user_id:  # invited as someone's caregiver: they can start right away, or register too
        out = {**await _session_for(request, response, result.user_id), **out, "signed_in": True}
    return out


@router.post("/auth/register")
async def register(body: RegisterIn, request: Request, response: Response) -> dict[str, Any]:
    try:
        user_id = await signin.register(
            request.app.state.app_pool,
            body.registration_token,
            name=body.name,
            dob=body.dob,
            city=body.city,
            settings=get_settings(),
        )
    except signin.SignInError as exc:
        raise _bad(exc) from exc
    return await _session_for(request, response, user_id, prefer="patient")


@router.post("/auth/role")
async def switch_role(body: RoleIn, request: Request, response: Response, auth: Auth) -> dict[str, Any]:
    roles = await signin.roles_for(request.app.state.app_pool, auth["user_id"])
    if body.role not in {r["role"] for r in roles}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That role isn't available to this account")
    return await _session_for(request, response, auth["user_id"], prefer=body.role)


@router.post("/auth/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(signin.COOKIE, path="/")
    return {"signed_out": True}


@router.get("/auth/demo-accounts")
async def demo_accounts(request: Request) -> list[dict[str, Any]]:
    """Development only: the seeded synthetic accounts and their numbers, so a demo can sign in quickly."""
    if get_settings().env != "dev":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    async with scoped_system(request.app.state.app_pool) as conn:
        rows = await (
            await conn.execute(
                "SELECT u.phone, u.role, COALESCE(p.name, d.name, u.display_name) AS name"
                " FROM app_user u LEFT JOIN patient p ON p.patient_id = u.patient_id"
                " LEFT JOIN doctor d ON d.doctor_id = u.doctor_id"
                " WHERE u.phone LIKE '+9198200000%%' ORDER BY u.phone"
            )
        ).fetchall()
    return cast(list[dict[str, Any]], rows)


@router.get("/me")
async def me(request: Request, auth: Auth) -> dict[str, Any]:
    pool = request.app.state.app_pool
    roles = await signin.roles_for(pool, auth["user_id"])
    return {
        **auth,
        **(await signin.profile(pool, auth["user_id"])),
        "roles": [r["role"] for r in roles] or [auth["role"]],
    }
