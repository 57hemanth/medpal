"""Doctor scribe review and signing endpoints."""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from langgraph.types import Command
from pydantic import BaseModel, Field, model_validator

from services.api.deps import auth_ctx
from services.api.tracing import traced
from services.platform.auth import AuthContext
from services.platform.egress.client import ModelUnavailable
from services.platform.phi.scrubber import BlockedIdentifier, EgressBlocked
from services.scribe.encounters import list_consultations, start_encounter
from services.scribe.service import AlreadySigned, SoapDraft, draft_note, sign_note
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


class QuickDraftOut(SoapDraft):
    rejected_medicines: list[str] = Field(default_factory=list)  # named by the model, not by the doctor


@router.post("/draft", response_model=QuickDraftOut)
async def draft(body: DraftIn, request: Request, auth: Auth) -> QuickDraftOut:
    if auth["role"] != "doctor":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only doctors can draft notes")
    try:
        soap, rejected = await draft_note(request.app.state.chat_client, transcript=body.transcript)
        return QuickDraftOut(**soap.model_dump(), rejected_medicines=rejected)
    except (EgressBlocked, BlockedIdentifier) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "transcript_blocked_by_privacy_gate"
        ) from exc
    except ModelUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "drafting_unavailable: write the note manually"
        ) from exc


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


# ---- consultations: encounters and the doctor-review session ------------------------------------


class StartEncounterIn(BaseModel):
    appt_id: str


class SessionIn(BaseModel):
    encounter_id: str
    transcript: str = Field(min_length=10, max_length=100_000)


class ReviewIn(BaseModel):
    """The doctor's decision on the draft: sign it, save edits (stock is re-checked), or reject it."""

    action: Literal["sign", "edit", "reject"]
    soap: dict[str, Any] | None = None  # sign and edit carry the exact note: the doctor signs what they send
    comments: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _note_required(self) -> "ReviewIn":
        if self.action in ("sign", "edit") and self.soap is None:
            raise ValueError(f"{self.action} must include the note being {self.action}ed")
        return self


class SessionOut(BaseModel):
    thread_id: str
    status: Literal["awaiting_review", "signed"]
    soap: dict[str, Any] | None = None
    medicines: list[str] = Field(default_factory=list)
    stock_flags: list[dict[str, Any]] = Field(default_factory=list)
    rejected_medicines: list[str] = Field(default_factory=list)
    drafting_unavailable: bool = False
    signed: dict[str, Any] | None = None


def _session_out(thread_id: str, out: dict[str, Any]) -> SessionOut:
    if out.get("__interrupt__"):
        value = out["__interrupt__"][0].value
        return SessionOut(
            thread_id=thread_id,
            status="awaiting_review",
            soap=value["soap"],
            medicines=value["medicines"],
            stock_flags=value["stock_flags"],
            rejected_medicines=value["rejected_medicines"],
            drafting_unavailable=value["drafting_unavailable"],
        )
    return SessionOut(thread_id=thread_id, status="signed", soap=out.get("soap"), signed=out.get("signed"))


def _doctor(auth: AuthContext) -> None:
    if auth["role"] != "doctor":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "consultations are for doctors")


@router.get("/consultations")
async def consultations(request: Request, auth: Auth) -> list[dict[str, Any]]:
    _doctor(auth)
    return await list_consultations(request.app.state.app_pool, auth)


@router.post("/encounters", status_code=status.HTTP_201_CREATED)
async def encounter(body: StartEncounterIn, request: Request, auth: Auth) -> dict[str, str]:
    _doctor(auth)
    try:
        encounter_id = await start_encounter(request.app.state.app_pool, auth, appt_id=body.appt_id)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return {"encounter_id": encounter_id}


async def _run(request: Request, thread_id: str, payload: Any) -> SessionOut:
    try:
        async with traced(request, "scribe", thread_id) as callbacks:
            out = await request.app.state.scribe_graph.ainvoke(
                payload, {"configurable": {"thread_id": thread_id}, "callbacks": callbacks}
            )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except AlreadySigned as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _session_out(thread_id, out)


@router.post("/sessions", response_model=SessionOut)
async def start_session(body: SessionIn, request: Request, auth: Auth) -> SessionOut:
    _doctor(auth)
    thread_id = str(uuid.uuid4())
    payload = {"auth": auth, "encounter_id": body.encounter_id, "transcript": body.transcript}
    return await _run(request, thread_id, payload)


@router.post("/sessions/{thread_id}/resume", response_model=SessionOut)
async def resume_session(thread_id: str, body: ReviewIn, request: Request, auth: Auth) -> SessionOut:
    _doctor(auth)
    snapshot = await request.app.state.scribe_graph.aget_state({"configurable": {"thread_id": thread_id}})
    owner = (snapshot.values or {}).get("auth", {}).get("user_id")
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown session")
    if owner != auth["user_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your session")
    if not snapshot.next:
        raise HTTPException(status.HTTP_409_CONFLICT, "this note is already signed")
    return await _run(request, thread_id, Command(resume=body.model_dump(exclude_none=True)))
