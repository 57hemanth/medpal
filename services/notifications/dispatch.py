"""Send due messages from the outbox.

Rows are claimed with FOR UPDATE SKIP LOCKED, so several API processes or workers can run this at once
without sending a message twice. Sending happens outside the claiming transaction (a slow mail server
must not hold row locks); a row left in `sending` by a crash is reclaimed after `RECLAIM_AFTER`, which
makes delivery at-least-once. Every send re-reads the appointment, so a cancellation that lands after a
reminder was queued still stops it.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from psycopg_pool import AsyncConnectionPool

from services.notifications.email import EmailSender, mask_email
from services.notifications.templates import Visit, appointment_email
from services.platform.config import Settings
from services.platform.db import scoped_system

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RECLAIM_AFTER = timedelta(minutes=10)


@dataclass
class DispatchReport:
    sent: int = 0
    skipped: int = 0
    cancelled: int = 0
    retried: int = 0
    failed: int = 0
    details: list[str] = field(default_factory=list)


_CLAIM = """
UPDATE notification_outbox o SET status = 'sending', claimed_at = now(), attempts = o.attempts + 1
 WHERE o.notification_id IN (
       SELECT notification_id FROM notification_outbox
        WHERE (status = 'queued' AND send_after <= now())
           OR (status = 'sending' AND claimed_at < now() - %(reclaim)s)
        ORDER BY send_after
        LIMIT %(limit)s
        FOR UPDATE SKIP LOCKED)
RETURNING o.notification_id::text
"""

_DETAILS = """
SELECT o.notification_id::text, o.kind, o.attempts, a.status AS appt_status, s.starts_at,
       p.name AS patient_name, p.email, p.email_verified_at, p.email_notifications,
       d.name AS doctor_name, c.name AS clinic_name, c.city
  FROM notification_outbox o
  JOIN patient p ON p.patient_id = o.patient_id
  LEFT JOIN appointment a ON a.appt_id = o.appt_id
  LEFT JOIN slot s ON s.slot_id = a.slot_id
  LEFT JOIN doctor d ON d.doctor_id = s.doctor_id
  LEFT JOIN clinic c ON c.clinic_id = s.clinic_id
 WHERE o.notification_id = ANY(%s::uuid[])
"""


def _decide(row: dict[str, Any]) -> str | None:
    """Why this message must not go, or None to send it."""
    if row["starts_at"] is None:
        return "appointment not found"
    if row["kind"] != "appointment_cancelled" and row["appt_status"] != "booked":
        return f"appointment {row['appt_status']}"
    if not row["email"]:
        return "no email address"
    if row["email_verified_at"] is None:
        return "email address not confirmed"
    if not row["email_notifications"]:
        return "appointment emails turned off"
    return None


async def _finish(pool: AsyncConnectionPool, notification_id: str, **values: Any) -> None:
    sets = ", ".join(f"{column} = %({column})s" for column in values)
    async with scoped_system(pool) as conn:
        await conn.execute(
            f"UPDATE notification_outbox SET {sets} WHERE notification_id = %(id)s",  # noqa: S608  fixed columns
            {**values, "id": notification_id},
        )


async def dispatch_due(
    pool: AsyncConnectionPool, sender: EmailSender, settings: Settings, *, limit: int = 50
) -> DispatchReport:
    report = DispatchReport()
    async with scoped_system(pool) as conn:
        cursor = await conn.execute(_CLAIM, {"reclaim": RECLAIM_AFTER, "limit": limit})
        claimed = [r["notification_id"] for r in cast(list[dict[str, Any]], await cursor.fetchall())]
        if not claimed:
            return report
        rows = cast(list[dict[str, Any]], await (await conn.execute(_DETAILS, (claimed,))).fetchall())

    for row in rows:
        notification_id = row["notification_id"]
        reason = _decide(row)
        if reason is not None:
            status = "cancelled" if reason.startswith("appointment ") else "skipped"
            await _finish(pool, notification_id, status=status, detail=reason)
            setattr(report, status, getattr(report, status) + 1)
            continue
        visit = Visit(
            row["patient_name"], row["doctor_name"], row["clinic_name"], row["city"], row["starts_at"]
        )
        email = appointment_email(row["kind"], visit, to=row["email"], base_url=settings.public_base_url)
        try:
            await sender.send(email)
        except Exception as exc:  # noqa: BLE001  any delivery failure is retried, then recorded
            error = f"{type(exc).__name__}: {str(exc)[:160]}"
            if row["attempts"] >= MAX_ATTEMPTS:
                await _finish(pool, notification_id, status="failed", detail=error)
                report.failed += 1
            else:
                backoff = timedelta(minutes=2 ** row["attempts"])
                async with scoped_system(pool) as conn:
                    await conn.execute(
                        "UPDATE notification_outbox SET status = 'queued', detail = %s,"
                        " send_after = now() + %s WHERE notification_id = %s",
                        (error, backoff, notification_id),
                    )
                report.retried += 1
            report.details.append(error)
            log.warning("email %s not sent: %s", row["kind"], error)
            continue
        await _finish(
            pool,
            notification_id,
            status="sent",
            sent_at=datetime.now(UTC),
            recipient=mask_email(row["email"]),
            subject=email.subject,
            detail=None,
        )
        report.sent += 1
    return report


async def run_forever(pool: AsyncConnectionPool, sender: EmailSender, settings: Settings) -> None:
    """The in-process sender for `notify_dispatch=inline`: poll, send, sleep. Never raises."""
    while True:
        try:
            report = await dispatch_due(pool, sender, settings)
            if report.sent or report.failed or report.retried:
                log.info("emails: %s", report)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001  a bad tick must not stop future sends
            log.exception("email dispatch failed; retrying next tick")
        await asyncio.sleep(settings.notify_poll_seconds)
