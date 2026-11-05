"""Doctor scribe review and signing endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from services.api.deps import auth_ctx
from services.platform.auth import AuthContext
from services.scribe.service import ScribeReviewNeeded, SoapDraft, draft_note, sign_note
from services.scribe.speech import MAX_AUDIO_BYTES, SpeechUnavailable

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


class TranscriptOut(BaseModel):
    transcript: str


@router.post(
    "/transcribe",
    response_model=TranscriptOut,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def transcribe(
    request: Request,
    auth: Auth,
) -> TranscriptOut:
    if auth["role"] != "doctor":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only doctors can transcribe consultations")
    # Stream a raw WAV body; multipart UploadFile can spool audio to disk before validation.
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_AUDIO_BYTES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "audio_too_large")
        content.extend(chunk)
    try:
        text = await request.app.state.speech_transcriber.transcribe(bytes(content))
    except SpeechUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return TranscriptOut(transcript=text)
