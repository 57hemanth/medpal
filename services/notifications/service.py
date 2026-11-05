"""A patient's email settings, address confirmation, and the record of messages sent."""

import time
from typing import Any, cast
from urllib.parse import quote

from psycopg_pool import AsyncConnectionPool

from services.notifications.email import EmailSender, mask_email
from services.notifications.templates import verification_email
from services.platform import audit
from services.platform.auth import AuthContext
from services.platform.config import Settings
from services.platform.db import scoped, scoped_system
from services.platform.signin import SignInError, sign, unsign

VERIFY_TTL_SECONDS = 24 * 3600


class ContactError(ValueError):
    """Shown to the person as is."""


def _own_patient(auth: AuthContext) -> str:
    if auth["role"] != "patient" or not auth["acting_for_patient_id"]:
        raise PermissionError("only a patient manages their own email settings")
    return auth["acting_for_patient_id"]


async def get_contact(pool: AsyncConnectionPool, auth: AuthContext) -> dict[str, Any]:
    patient_id = _own_patient(auth)
    async with scoped(pool, auth) as conn:
        row = await (
            await conn.execute(
                "SELECT email, email_verified_at IS NOT NULL AS email_verified, email_notifications"
                " FROM patient WHERE patient_id = %s",
                (patient_id,),
            )
        ).fetchone()
    if row is None:
        raise PermissionError("patient not visible")
    return cast(dict[str, Any], row)


async def update_contact(
    pool: AsyncConnectionPool,
    auth: AuthContext,
    sender: EmailSender,
    settings: Settings,
    *,
    email: str | None,
    email_notifications: bool,
) -> dict[str, Any]:
    patient_id = _own_patient(auth)
    address = (email or "").strip().lower() or None
    if address and ("@" not in address or "." not in address.rpartition("@")[2] or len(address) > 254):
        raise ContactError("That doesn't look like an email address")
    async with scoped(pool, auth) as conn:
        before = cast(
            dict[str, Any] | None,
            await (
                await conn.execute("SELECT email, name FROM patient WHERE patient_id = %s", (patient_id,))
            ).fetchone(),
        )
        if before is None:
            raise PermissionError("patient not visible")
        await conn.execute(
            "UPDATE patient SET email = %s, email_notifications = %s WHERE patient_id = %s",
            (address, email_notifications, patient_id),
        )
        await audit.write(
            conn,
            auth,
            action="update",
            resource="patient_contact",
            record_id=patient_id,
            patient_id=patient_id,
            purpose="email settings",
        )
    changed = address is not None and address != before["email"]
    if changed:
        await send_verification(pool, auth, sender, settings)
    return await get_contact(pool, auth)


async def send_verification(
    pool: AsyncConnectionPool, auth: AuthContext, sender: EmailSender, settings: Settings
) -> None:
    patient_id = _own_patient(auth)
    async with scoped(pool, auth) as conn:
        row = cast(
            dict[str, Any] | None,
            await (
                await conn.execute(
                    "SELECT name, email, email_verified_at FROM patient WHERE patient_id = %s", (patient_id,)
                )
            ).fetchone(),
        )
    if row is None or not row["email"]:
        raise ContactError("Add an email address first")
    if row["email_verified_at"] is not None:
        raise ContactError("This address is already confirmed")
    token = sign(
        {
            "purpose": "verify_email",
            "p": patient_id,
            "e": row["email"],
            "exp": time.time() + VERIFY_TTL_SECONDS,
        },
        settings,
    )
    link = f"{settings.public_base_url}/api/me/email/verify?token={quote(token)}"
    await sender.send(verification_email(row["name"], to=row["email"], link=link))


async def confirm_email(pool: AsyncConnectionPool, token: str, settings: Settings) -> bool:
    """The link in the confirmation email. Confirms only the address it was sent to, and only if unchanged."""
    try:
        claims = unsign(token, settings, purpose="verify_email")
    except SignInError:
        return False
    async with scoped_system(pool) as conn:
        cursor = await conn.execute(
            "UPDATE patient SET email_verified_at = now()"
            " WHERE patient_id = %s AND email = %s AND email_verified_at IS NULL",
            (claims["p"], claims["e"]),
        )
        updated = cursor.rowcount == 1
        already = await (
            await conn.execute(
                "SELECT 1 FROM patient"
                " WHERE patient_id = %s AND email = %s AND email_verified_at IS NOT NULL",
                (claims["p"], claims["e"]),
            )
        ).fetchone()
    return updated or already is not None


async def list_messages(
    pool: AsyncConnectionPool, auth: AuthContext, *, limit: int = 200
) -> list[dict[str, Any]]:
    """Messages the caller may see (row-level security decides): their own, or all for desk and compliance."""
    async with scoped(pool, auth) as conn:
        rows = await (
            await conn.execute(
                "SELECT o.notification_id::text, o.kind, o.channel, o.status, o.send_after, o.sent_at,"
                " o.recipient, o.subject, o.detail, o.attempts, o.created_at, s.starts_at,"
                " p.name AS patient_name, d.name AS doctor_name"
                " FROM notification_outbox o"
                " LEFT JOIN patient p ON p.patient_id = o.patient_id"
                " LEFT JOIN appointment a ON a.appt_id = o.appt_id"
                " LEFT JOIN slot s ON s.slot_id = a.slot_id"
                " LEFT JOIN doctor d ON d.doctor_id = s.doctor_id"
                " ORDER BY COALESCE(o.sent_at, o.send_after) DESC LIMIT %s",
                (max(1, min(limit, 500)),),
            )
        ).fetchall()
    return cast(list[dict[str, Any]], rows)


__all__ = ["ContactError", "confirm_email", "get_contact", "list_messages", "mask_email", "update_contact"]
