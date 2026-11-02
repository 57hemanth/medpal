"""Doctor scribe review and signing endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from services.api.deps import auth_ctx
from services.platform.auth import AuthContext
from services.scribe.service import ScribeReviewNeeded, SoapDraft, draft_note, sign_note

router = APIRouter(prefix="/api/scribe", tags=["scribe"])

Auth = Annotated[AuthContext, Depends(auth_ctx)]


class DraftIn(BaseModel):
    transcript: str = Field(min_length=10)


class SignIn(BaseModel):
    encounter_id: str
    draft: SoapDraft
    soap_json: dict[str, Any]
    edit_history: list[dict[str, Any]] = Field(default_factory=list)


class SignedOut(BaseModel):
    note_id: str
    version: int
    content_hash: str


@router.post("/draft", response_model=SoapDraft)
async def draft(body: DraftIn, request: Request, auth: Auth) -> SoapDraft:
    if auth["role"] != "doctor":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only doctors can draft notes")
    try:
        return await draft_note(request.app.state.chat_client, transcript=body.transcript)
    except ScribeReviewNeeded as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/sign", response_model=SignedOut)
async def sign(body: SignIn, request: Request, auth: Auth) -> SignedOut:
    try:
        signed = await sign_note(
            request.app.state.app_pool,
            auth,
            encounter_id=body.encounter_id,
            draft=body.draft,
            edited_soap=body.soap_json,
            edit_history=body.edit_history,
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return SignedOut(**signed.__dict__)
