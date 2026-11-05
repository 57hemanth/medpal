"""Consultation scribe draft and signing workflow."""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from services.platform import audit
from services.platform.auth import AuthContext
from services.platform.db import scoped
from services.platform.egress.client import EgressChatClient, ModelRequest
from services.scribe.stock import ground_medicines


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


class AlreadySigned(ValueError):
    """Signed notes are immutable; an amendment would be a new version, not a second first version."""


def _canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def content_hash(soap_json: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(soap_json).encode()).hexdigest()


DRAFT_INSTRUCTIONS = (
    "Draft a SOAP note from the consultation transcript. Structure what was said; never add a diagnosis, "
    "medicine, dose or test the doctor did not state. If the doctor names a drug class without a molecule "
    "or dose, write it in the plan followed by '[doctor to specify]'. The medicines list holds only drug "
    "names exactly as spoken in the transcript (for example 'paracetamol'), with no doses, classes or "
    "placeholders; leave it empty if no drug was named."
)


async def request_draft(chat: EgressChatClient, *, transcript: str, comments: str | None = None) -> SoapDraft:
    """Ask the model for a draft. No medicine validation here: the scribe graph grounds medicines itself
    and shows the doctor anything it had to reject."""
    user = transcript if not comments else f"{transcript}\n\nThe doctor rejected the last draft: {comments}"
    return await chat.ask_structured(
        ModelRequest(system=DRAFT_INSTRUCTIONS, user=user, purpose="scribe draft"),
        SoapDraft,
    )


async def draft_note(
    chat: EgressChatClient, *, transcript: str, comments: str | None = None
) -> tuple[SoapDraft, list[str]]:
    """One-shot draft for the quick-draft endpoint: (draft, rejected medicines).

    Same rule as the review graph: a medicine stays only if the transcript names it; anything else the
    model listed is returned as rejected, for the doctor to see, rather than failing the whole draft.
    """
    draft = await request_draft(chat, transcript=transcript, comments=comments)
    grounded, rejected = ground_medicines(transcript, draft.medicines, formulary=[])
    return draft.model_copy(update={"medicines": grounded}), rejected


async def sign_note(
    pool: AsyncConnectionPool,
    auth: AuthContext,
    *,
    encounter_id: str,
    draft: SoapDraft,
    edited_soap: dict[str, Any],
    edit_history: list[dict[str, Any]] | None = None,
    medicines: list[str] | None = None,
    transcript: str | None = None,
) -> SignedNote:
    """Persist the signed note and its prescription lines in ONE transaction. Only the encounter's doctor."""
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
        already = await (
            await conn.execute("SELECT 1 FROM note_version WHERE encounter_id = %s LIMIT 1", (encounter_id,))
        ).fetchone()
        if already:
            raise AlreadySigned("this consultation already has a signed note")
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
        if transcript:
            # The brief: the transcript and the note are kept (audio is not).
            await conn.execute(
                "UPDATE encounter SET transcript = %s WHERE encounter_id = %s", (transcript, encounter_id)
            )
        for medicine in medicines or []:
            # Same rule as the stock check: the name, else a composition that starts with it. Each
            # matched line is reserved at the consultation's clinic by a trigger, in this transaction.
            match = await (
                await conn.execute(
                    "SELECT medicine_id::text FROM medicine"
                    " WHERE lower(name) = lower(%s) OR lower(composition) LIKE lower(%s) || ' %%'"
                    " ORDER BY (lower(name) = lower(%s)) DESC LIMIT 1",
                    (medicine, medicine, medicine),
                )
            ).fetchone()
            await conn.execute(
                "INSERT INTO prescription (note_id, note_version, patient_id, medicine_id, medicine_text,"
                " dose, substitute_ok, set_by) VALUES (%s, 1, %s, %s, %s, %s, false, %s)",
                (
                    note_id,
                    row["patient_id"],
                    cast(dict[str, Any], match)["medicine_id"] if match else None,
                    medicine,
                    "as written in the signed note",
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


async def list_notes(
    pool: AsyncConnectionPool, auth: AuthContext, *, limit: int = 100
) -> list[dict[str, Any]]:
    """Signed notes the caller may read (row-level security decides): a doctor's own patients, a patient's
    own visits, a consented caregiver's, or compliance. Each with its prescriptions and their pharmacy
    status, and the transcript it was drafted from. Reading notes is audited like reading records."""
    async with scoped(pool, auth) as conn:
        rows = cast(
            list[dict[str, Any]],
            await (
                await conn.execute(
                    "SELECT n.note_id::text, n.version, n.signed_at, n.soap_json, n.edit_history,"
                    " n.content_hash, n.patient_id::text, p.name AS patient_name, d.name AS doctor_name,"
                    " c.name AS clinic_name,"
                    " e.transcript,"
                    " COALESCE((SELECT json_agg(json_build_object('rx_id', rx.rx_id,"
                    "     'medicine', rx.medicine_text,"
                    "     'status', r.status, 'clinic', rc.name, 'rx_status', rx.status,"
                    "     'stop_reason', rx.stop_reason, 'stopped_at', rx.stopped_at,"
                    "     'replaces', (SELECT o.medicine_text FROM prescription o"
                    "                  WHERE o.rx_id = rx.replaces_rx_id))"
                    "     ORDER BY rx.created_at, rx.medicine_text)"
                    "   FROM prescription rx"
                    "   LEFT JOIN medicine_reservation r ON r.rx_id = rx.rx_id"
                    "   LEFT JOIN clinic rc ON rc.clinic_id = r.clinic_id"
                    "   WHERE rx.note_id = n.note_id), '[]') AS prescriptions,"
                    # Earlier versions, newest first, so an amendment never hides what was signed before.
                    " COALESCE((SELECT json_agg(json_build_object('version', o.version,"
                    "     'signed_at', o.signed_at,"
                    "     'soap_json', o.soap_json) ORDER BY o.version DESC)"
                    "   FROM note_version o WHERE o.note_id = n.note_id AND o.version < n.version), '[]')"
                    "   AS earlier_versions,"
                    " (n.doctor_id = (SELECT u.doctor_id FROM app_user u WHERE u.user_id = app_user_id()))"
                    "   AS mine"
                    " FROM note_version n"
                    " LEFT JOIN patient p ON p.patient_id = n.patient_id"
                    " LEFT JOIN doctor d ON d.doctor_id = n.doctor_id"
                    " LEFT JOIN encounter e ON e.encounter_id = n.encounter_id"
                    " LEFT JOIN appointment a ON a.appt_id = e.appt_id"
                    " LEFT JOIN slot s ON s.slot_id = a.slot_id"
                    " LEFT JOIN clinic c ON c.clinic_id = s.clinic_id"
                    " WHERE n.version = (SELECT max(v.version) FROM note_version v"
                    "                    WHERE v.note_id = n.note_id)"
                    " ORDER BY n.signed_at DESC LIMIT %s",
                    (max(1, min(limit, 300)),),
                )
            ).fetchall(),
        )
        for row in rows:
            await audit.write(
                conn,
                auth,
                action="read",
                resource="note_version",
                record_id=row["note_id"],
                patient_id=row["patient_id"],
                purpose="view consultation notes",
            )
    return rows


# ---- after signing: amendments and prescription changes -------------------------------------------

SOAP_FIELDS = ("subjective", "objective", "assessment", "plan")


class ChangeRefused(ValueError):
    """Shown to the doctor as is."""


async def amend_note(
    pool: AsyncConnectionPool, auth: AuthContext, *, note_id: str, soap: dict[str, str], reason: str
) -> SignedNote:
    """A new version of a signed note, by the doctor who signed it. The earlier versions are untouched
    (a trigger forbids changing them); the history records which sections changed and why."""
    if auth["role"] != "doctor":
        raise PermissionError("only doctors amend notes")
    reason = reason.strip()
    if not reason:
        raise ChangeRefused("Say why the note is being amended")
    async with scoped(pool, auth) as conn:
        latest = cast(
            dict[str, Any] | None,
            await (
                await conn.execute(
                    "SELECT n.version, n.encounter_id::text, n.patient_id::text, n.doctor_id::text,"
                    " n.soap_json, n.draft_json, n.edit_history"
                    " FROM note_version n JOIN app_user u ON u.doctor_id = n.doctor_id AND u.user_id = %s"
                    " WHERE n.note_id = %s ORDER BY n.version DESC LIMIT 1",
                    (auth["user_id"], note_id),
                )
            ).fetchone(),
        )
        if latest is None:
            raise PermissionError("only the doctor who signed a note can amend it")
        new_soap = {**latest["soap_json"], **{k: soap[k].strip() for k in SOAP_FIELDS if k in soap}}
        changed = [k for k in SOAP_FIELDS if new_soap.get(k) != latest["soap_json"].get(k)]
        if not changed:
            raise ChangeRefused("Nothing in the note has changed")
        version = latest["version"] + 1
        history = [
            *latest["edit_history"],
            {
                "action": "amended",
                "version": version,
                "fields": changed,
                "reason": reason[:300],
                "at": datetime.now(UTC).isoformat(),
            },
        ]
        digest = content_hash(new_soap)
        await conn.execute(
            "INSERT INTO note_version (note_id, version, encounter_id, patient_id, doctor_id,"
            " soap_json, draft_json, edit_history, content_hash, signed_by)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                note_id,
                version,
                latest["encounter_id"],
                latest["patient_id"],
                latest["doctor_id"],
                json.dumps(new_soap),
                json.dumps(latest["draft_json"]),
                json.dumps(history),
                digest,
                auth["user_id"],
            ),
        )
        await audit.write(
            conn,
            auth,
            action="amend",
            resource="note_version",
            record_id=note_id,
            patient_id=latest["patient_id"],
            purpose=f"amend note to version {version}",
        )
    return SignedNote(note_id=note_id, version=version, content_hash=digest)


async def _medicine_match(conn: Any, medicine: str) -> str | None:
    match = await (
        await conn.execute(
            "SELECT medicine_id::text FROM medicine"
            " WHERE lower(name) = lower(%s) OR lower(composition) LIKE lower(%s) || ' %%'"
            " ORDER BY (lower(name) = lower(%s)) DESC LIMIT 1",
            (medicine, medicine, medicine),
        )
    ).fetchone()
    return cast(dict[str, Any], match)["medicine_id"] if match else None


async def change_prescription(
    pool: AsyncConnectionPool,
    auth: AuthContext,
    *,
    rx_id: str,
    reason: str,
    replacement: str | None = None,
) -> dict[str, Any]:
    """Stop a prescription (and, if given, prescribe a replacement in its place) in one transaction.
    Only the prescribing doctor. The pharmacy hold is released and the patient gets a fixed message;
    a replacement is held at the same clinic if it's in stock, like any prescription at signing."""
    if auth["role"] != "doctor":
        raise PermissionError("only doctors change prescriptions")
    reason = reason.strip()
    replacement = (replacement or "").strip() or None
    if not reason:
        raise ChangeRefused("Say why the prescription is being changed")
    async with scoped(pool, auth) as conn:
        rx = cast(
            dict[str, Any] | None,
            await (
                await conn.execute(
                    "SELECT rx.note_id::text, rx.note_version, rx.patient_id::text, rx.medicine_text,"
                    " rx.status"
                    " FROM prescription rx WHERE rx.rx_id = %s",
                    (rx_id,),
                )
            ).fetchone(),
        )
        if rx is None:
            raise LookupError("no such prescription")
        if rx["status"] != "active":
            raise ChangeRefused("This prescription has already been stopped")
        message = (
            f"Your doctor changed your prescription: {rx['medicine_text']} was replaced by {replacement}."
            if replacement
            else f"Your doctor stopped your prescription for {rx['medicine_text']}. Don't continue it "
            "unless your doctor tells you to."
        )
        stopped = await (
            await conn.execute("SELECT stop_prescription(%s, %s, %s) AS ok", (rx_id, reason, message))
        ).fetchone()
        if not cast(dict[str, Any], stopped)["ok"]:
            raise PermissionError("only the prescribing doctor can change this prescription")
        new_rx: str | None = None
        if replacement:
            row = await (
                await conn.execute(
                    "INSERT INTO prescription (note_id, note_version, patient_id, medicine_id, medicine_text,"
                    " dose, substitute_ok, set_by, replaces_rx_id)"
                    " VALUES (%s, %s, %s, %s, %s, %s, false, %s, %s)"
                    " RETURNING rx_id::text",
                    (
                        rx["note_id"],
                        rx["note_version"],
                        rx["patient_id"],
                        await _medicine_match(conn, replacement),
                        replacement[:200],
                        "as directed by the doctor",
                        auth["user_id"],
                        rx_id,
                    ),
                )
            ).fetchone()
            new_rx = cast(dict[str, Any], row)["rx_id"]
        await audit.write(
            conn,
            auth,
            action="update",
            resource="prescription",
            record_id=rx_id,
            patient_id=rx["patient_id"],
            purpose="replace prescription" if replacement else "stop prescription",
        )
    return {"rx_id": rx_id, "status": "stopped", "replacement_rx_id": new_rx}
