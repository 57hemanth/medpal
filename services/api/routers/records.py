"""Records upload and ingest status endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from services.api.deps import auth_ctx
from services.platform.auth import AuthContext
from services.records.ingest import UploadRejected
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


@router.post("", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def upload(
    request: Request,
    auth: Auth,
    patient_id: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> UploadOut:
    if auth["role"] != "patient":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "records upload is available to patients first")
    content = await file.read()
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
