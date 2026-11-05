"""Consent lifecycle endpoints."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from services.api.deps import auth_ctx
from services.platform.auth import AuthContext
from services.records.consent import grant_consent, grant_consent_to_phone, list_consents, revoke_consent

router = APIRouter(prefix="/api/consents", tags=["consent"])

Auth = Annotated[AuthContext, Depends(auth_ctx)]


class ConsentOut(BaseModel):
    consent_id: str
    patient_id: str
    grantee_user_id: str
    scope: list[str]
    purpose: str
    expires_at: datetime
    revoked_at: datetime | None
    patient_name: str | None = None
    grantee_name: str | None = None


class GrantConsentIn(BaseModel):
    patient_id: str
    grantee_user_id: str
    scope: list[str] = Field(min_length=1)
    purpose: str = Field(min_length=3, max_length=200)
    expires_at: datetime


@router.get("", response_model=list[ConsentOut])
async def list_(request: Request, auth: Auth) -> list[ConsentOut]:
    return [ConsentOut(**grant.__dict__) for grant in await list_consents(request.app.state.app_pool, auth)]


@router.post("", response_model=ConsentOut, status_code=status.HTTP_201_CREATED)
async def grant(body: GrantConsentIn, request: Request, auth: Auth) -> ConsentOut:
    try:
        result = await grant_consent(
            request.app.state.app_pool,
            auth,
            patient_id=body.patient_id,
            grantee_user_id=body.grantee_user_id,
            scope=body.scope,
            purpose=body.purpose,
            expires_at=body.expires_at,
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return ConsentOut(**result.__dict__)


class ShareIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    scope: list[Literal["records:read", "appointments:read"]] = Field(min_length=1)
    purpose: str = Field(min_length=3, max_length=200)
    days: int = Field(ge=1, le=365)


@router.post("/share", response_model=ConsentOut, status_code=status.HTTP_201_CREATED)
async def share(body: ShareIn, request: Request, auth: Auth) -> ConsentOut:
    """Share your own record with a mobile number, for a purpose and a set number of days."""
    try:
        result = await grant_consent_to_phone(
            request.app.state.app_pool,
            auth,
            phone=body.phone,
            scope=list(dict.fromkeys(body.scope)),
            purpose=body.purpose,
            days=body.days,
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return ConsentOut(**result.__dict__)


@router.post("/{consent_id}/revoke", response_model=ConsentOut)
async def revoke(consent_id: str, request: Request, auth: Auth) -> ConsentOut:
    try:
        result = await revoke_consent(request.app.state.app_pool, auth, consent_id=consent_id)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return ConsentOut(**result.__dict__)
