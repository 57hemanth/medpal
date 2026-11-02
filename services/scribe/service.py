"""Consultation scribe draft and signing workflow."""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, cast

from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from services.platform import audit
from services.platform.auth import AuthContext
from services.platform.db import scoped
from services.platform.egress.client import EgressChatClient, ModelRequest


class SoapDraft(BaseModel):
    subjective: str
    objective: str
    assessment: str
    plan: str
    medicines: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class SignedNote:
    note_id: str
    version: int
    content_hash: str


class ScribeReviewNeeded(ValueError):
    pass


def _canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def content_hash(soap_json: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(soap_json).encode()).hexdigest()


def validate_medicine_evidence(draft: SoapDraft, transcript: str) -> None:
    lowered = transcript.lower()
    missing = [medicine for medicine in draft.medicines if medicine.lower() not in lowered]
    if missing:
        raise ScribeReviewNeeded(f"medicine_not_in_transcript:{','.join(missing)}")


async def draft_note(chat: EgressChatClient, *, transcript: str) -> SoapDraft:
    draft = await chat.ask_structured(
        ModelRequest(
            system="Draft a SOAP note from the transcript. Do not add medicines absent from the transcript.",
            user=transcript,
            purpose="scribe draft",
        ),
        SoapDraft,
    )
    validate_medicine_evidence(draft, transcript)
    return draft


async def sign_note(
    pool: AsyncConnectionPool,
    auth: AuthContext,
    *,
    encounter_id: str,
    draft: SoapDraft,
    edited_soap: dict[str, Any],
    edit_history: list[dict[str, Any]] | None = None,
) -> SignedNote:
    if auth["role"] != "doctor":
        raise PermissionError("only doctors can sign notes")
    note_id = str(uuid.uuid4())
    digest = content_hash(edited_soap)
    async with scoped(pool, auth) as conn:
        encounter = await (
            await conn.execute(
                "SELECT encounter_id::text, patient_id::text, doctor_id::text"
                " FROM encounter WHERE encounter_id = %s",
                (encounter_id,),
            )
        ).fetchone()
        if encounter is None:
            raise PermissionError("encounter is not visible")
        row = cast(dict[str, Any], encounter)
        await conn.execute(
            "INSERT INTO note_version (note_id, version, encounter_id, patient_id, doctor_id,"
            " soap_json, draft_json, edit_history, content_hash, signed_by)"
            " VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                note_id,
                encounter_id,
                row["patient_id"],
                row["doctor_id"],
                json.dumps(edited_soap),
                draft.model_dump_json(),
                json.dumps(edit_history or []),
                digest,
                auth["user_id"],
            ),
        )
        await audit.write(
            conn,
            auth,
            action="sign",
            resource="note_version",
            record_id=note_id,
            patient_id=str(row["patient_id"]),
            purpose="consultation scribe",
        )
    return SignedNote(note_id=note_id, version=1, content_hash=digest)
