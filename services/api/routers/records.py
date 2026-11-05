"""Records upload and ingest status endpoints."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from services.api.deps import auth_ctx
from services.api.tracing import traced
from services.platform.auth import AuthContext
from services.records.ingest import MAX_UPLOAD_BYTES, UploadRejected
from services.records.ingest_graph import job_id
from services.records.qa import answer_question
from services.records.service import ingest_record, list_records, upload_record

router = APIRouter(prefix="/api/records", tags=["records"])

Auth = Annotated[AuthContext, Depends(auth_ctx)]


class UploadOut(BaseModel):
    doc_id: str
    job_id: str
    status: str
    sha256: str


class RecordOut(BaseModel):
    doc_id: str
    patient_id: str
    type: str
    sha256: str
    uploaded_at: Any
    phi_status: str
    status: str | None = None
    error: str | None = None


class QuestionIn(BaseModel):
    question: str
    # Required for caregivers (whose record?); ignored for patients, who always ask about their own.
    patient_id: str | None = None


class CitationOut(BaseModel):
    chunk_id: str
    doc_id: str
    page: int
    text: str


class AnswerOut(BaseModel):
    status: str
    answer: str
    citations: list[CitationOut]


@router.post("", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def upload(
    request: Request,
    auth: Auth,
    patient_id: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> UploadOut:
    if auth["role"] != "patient":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "records upload is available to patients first")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        uploaded_record = await upload_record(
            request.app.state.app_pool,
            request.app.state.object_store,
            auth,
            patient_id=patient_id,
            filename=file.filename or "record",
            content=content,
            content_type=file.content_type or "application/octet-stream",
        )
        queue = getattr(request.app.state, "ingest_queue", None)
        if queue is not None:
            # Only the id is queued; the worker reads the content from the object store.
            await queue.enqueue_job(
                "ingest_document", uploaded_record.doc_id, _job_id=job_id(uploaded_record.doc_id)
            )
            status_after_ingest = "queued"
        else:
            status_after_ingest = await ingest_record(
                request.app.state.app_pool, request.app.state.object_store, doc_id=uploaded_record.doc_id
            )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except UploadRejected as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.reason) from exc
    return UploadOut(**uploaded_record.__dict__).model_copy(update={"status": status_after_ingest})


@router.get("", response_model=list[RecordOut])
async def records(request: Request, auth: Auth) -> list[RecordOut]:
    return [RecordOut(**row) for row in await list_records(request.app.state.app_pool, auth)]


@router.post("/questions", response_model=AnswerOut)
async def question(body: QuestionIn, request: Request, auth: Auth) -> AnswerOut:
    trace_id = str(uuid.uuid4())
    async with traced(request, "records", trace_id):
        result = await answer_question(
            request.app.state.app_pool,
            request.app.state.chat_client,
            auth,
            question=body.question,
            patient_id=body.patient_id,
            trace_id=trace_id,
        )
    return AnswerOut(
        status=result.status,
        answer=result.answer,
        citations=[
            CitationOut(chunk_id=c.chunk_id, doc_id=c.doc_id, page=c.page, text=c.text)
            for c in result.citations
        ],
    )
