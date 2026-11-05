"""Appointment emails against real Postgres: what gets queued, what gets sent, and what must never be."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import psycopg
import pytest

from services.notifications import service
from services.notifications.dispatch import MAX_ATTEMPTS, dispatch_due
from services.notifications.email import Email
from services.platform.config import get_settings
from services.platform.db import scoped

pytestmark = pytest.mark.integration


class Outbox:
    """Records what would have been sent; can be told to fail."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[Email] = []
        self.fail = fail

    async def send(self, email: Email) -> None:
        if self.fail:
            raise ConnectionError("mail server down")
        await asyncio.sleep(0)  # let concurrent dispatchers interleave
        self.sent.append(email)

    def to(self, address: str) -> list[Email]:
        return [e for e in self.sent if e.to == address]


def _auth(world: dict[str, str]) -> Any:
    return {"user_id": world["user"], "role": "patient", "acting_for_patient_id": world["patient"]}


def _email(world: dict[str, str]) -> str:
    return f"p{world['patient'][:8]}@example.com"


def _confirm(admin_url: str, world: dict[str, str], email: str | None = None) -> None:
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute(
            "UPDATE patient SET email = %s WHERE patient_id = %s", (email or _email(world), world["patient"])
        )
        conn.execute("SELECT set_config('app.role', 'system', true)")
        conn.execute(
            "UPDATE patient SET email_verified_at = now() WHERE patient_id = %s", (world["patient"],)
        )


def _book(admin_url: str, world: dict[str, str], *, in_hours: float = 72) -> str:
    appt, slot = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute(
            "INSERT INTO slot (slot_id, doctor_id, clinic_id, starts_at, capacity)"
            " VALUES (%s, %s, %s, %s, 1)",
            (slot, world["doctor"], world["clinic"], datetime.now(UTC) + timedelta(hours=in_hours)),
        )
        conn.execute(
            "INSERT INTO appointment"
            " (appt_id, patient_id, slot_id, status, source, idempotency_key, created_by)"
            " VALUES (%s, %s, %s, 'booked', 'assistant', %s, %s)",
            (appt, world["patient"], slot, f"k-{appt}", world["user"]),
        )
    return appt


def _rows(admin_url: str, appt: str) -> dict[str, dict[str, Any]]:
    with psycopg.connect(admin_url, row_factory=psycopg.rows.dict_row) as conn:
        rows = conn.execute(
            "SELECT kind, status, send_after, recipient, subject, detail, attempts FROM notification_outbox"
            " WHERE appt_id = %s",
            (appt,),
        ).fetchall()
    return {r["kind"]: r for r in rows}


async def test_booking_queues_a_confirmation_and_two_reminders_and_sends_only_what_is_due(
    pool, world, admin_url
):
    _confirm(admin_url, world)
    appt = _book(admin_url, world, in_hours=72)
    queued = _rows(admin_url, appt)
    assert set(queued) == {"appointment_booked", "appointment_reminder_24h", "appointment_reminder_2h"}
    assert all(r["status"] == "queued" for r in queued.values())

    sender = Outbox()
    await dispatch_due(pool, sender, get_settings())
    [mail] = sender.to(_email(world))
    assert mail.subject.startswith("Appointment confirmed")
    assert "Dr " in mail.text and "Clinic" in mail.text
    assert world["specialty_name"] not in mail.text + mail.html  # a specialty can reveal a condition
    after = _rows(admin_url, appt)
    assert after["appointment_booked"]["status"] == "sent"
    assert after["appointment_booked"]["recipient"].endswith("•••@example.com")
    assert after["appointment_reminder_24h"]["status"] == "queued"  # not due for two days


async def test_a_visit_within_a_day_gets_no_24_hour_reminder(admin_url, world):
    appt = _book(admin_url, world, in_hours=5)
    assert set(_rows(admin_url, appt)) == {"appointment_booked", "appointment_reminder_2h"}


async def test_cancelling_withdraws_reminders_and_sends_a_cancellation(pool, world, admin_url):
    _confirm(admin_url, world)
    appt = _book(admin_url, world)
    async with scoped(pool, _auth(world)) as conn:
        await conn.execute("UPDATE appointment SET status = 'cancelled' WHERE appt_id = %s", (appt,))
    rows = _rows(admin_url, appt)
    assert rows["appointment_reminder_24h"]["status"] == "cancelled"
    assert rows["appointment_reminder_2h"]["status"] == "cancelled"
    assert rows["appointment_booked"]["status"] == "cancelled"  # never sent: the booking is already gone
    sender = Outbox()
    await dispatch_due(pool, sender, get_settings())
    [mail] = sender.to(_email(world))
    assert mail.subject.startswith("Appointment cancelled")


async def test_a_reminder_already_queued_is_not_sent_for_a_cancelled_visit(pool, world, admin_url):
    """Even if the cancellation lands after the row was due (a race), the send-time check stops it."""
    _confirm(admin_url, world)
    appt = _book(admin_url, world)
    with psycopg.connect(admin_url) as conn, conn.transaction():
        conn.execute("ALTER TABLE appointment DISABLE TRIGGER appointment_notifications")
        conn.execute("UPDATE appointment SET status = 'cancelled' WHERE appt_id = %s", (appt,))
        conn.execute("ALTER TABLE appointment ENABLE TRIGGER appointment_notifications")
        conn.execute("UPDATE notification_outbox SET send_after = now() WHERE appt_id = %s", (appt,))
    sender = Outbox()
    await dispatch_due(pool, sender, get_settings())
    assert sender.to(_email(world)) == []
    assert {r["status"] for r in _rows(admin_url, appt).values()} == {"cancelled"}


async def test_nothing_goes_to_an_unconfirmed_address(pool, world, admin_url):
    with psycopg.connect(admin_url) as conn:
        conn.execute("UPDATE patient SET email = %s WHERE patient_id = %s", (_email(world), world["patient"]))
    appt = _book(admin_url, world)
    sender = Outbox()
    await dispatch_due(pool, sender, get_settings())
    assert sender.to(_email(world)) == []
    booked = _rows(admin_url, appt)["appointment_booked"]
    assert (booked["status"], booked["detail"]) == ("skipped", "email address not confirmed")


async def test_turning_emails_off_is_respected(pool, world, admin_url):
    _confirm(admin_url, world)
    with psycopg.connect(admin_url) as conn:
        conn.execute(
            "UPDATE patient SET email_notifications = false WHERE patient_id = %s", (world["patient"],)
        )
    appt = _book(admin_url, world)
    sender = Outbox()
    await dispatch_due(pool, sender, get_settings())
    assert sender.to(_email(world)) == []
    assert _rows(admin_url, appt)["appointment_booked"]["detail"] == "appointment emails turned off"


async def test_a_patient_cannot_confirm_their_own_address_and_a_new_address_needs_confirming(
    pool, world, admin_url
):
    _confirm(admin_url, world)
    sender, settings = Outbox(), get_settings()
    out = await service.update_contact(
        pool, _auth(world), sender, settings, email="new-" + _email(world), email_notifications=True
    )
    assert out["email_verified"] is False  # changing the address clears the confirmation
    async with scoped(pool, _auth(world)) as conn:  # straight to the column: the trigger ignores it
        await conn.execute(
            "UPDATE patient SET email_verified_at = now() WHERE patient_id = %s", (world["patient"],)
        )
    assert (await service.get_contact(pool, _auth(world)))["email_verified"] is False

    [mail] = sender.to("new-" + _email(world))
    token = parse_qs(urlsplit(mail.text.split("Confirm email: ")[1].strip()).query)["token"][0]
    assert await service.confirm_email(pool, token, settings) is True
    assert (await service.get_contact(pool, _auth(world)))["email_verified"] is True


async def test_a_confirmation_link_for_an_old_address_does_not_confirm_a_new_one(pool, world, admin_url):
    sender, settings = Outbox(), get_settings()
    await service.update_contact(
        pool, _auth(world), sender, settings, email=_email(world), email_notifications=True
    )
    old_link = sender.to(_email(world))[0].text.split("Confirm email: ")[1].strip()
    await service.update_contact(
        pool, _auth(world), sender, settings, email="other-" + _email(world), email_notifications=True
    )
    token = parse_qs(urlsplit(old_link).query)["token"][0]
    assert await service.confirm_email(pool, token, settings) is False
    assert await service.confirm_email(pool, "forged.token", settings) is False
    assert (await service.get_contact(pool, _auth(world)))["email_verified"] is False


async def test_a_failing_mail_server_is_retried_with_backoff_then_recorded(pool, world, admin_url):
    _confirm(admin_url, world)
    appt = _book(admin_url, world)
    await dispatch_due(pool, Outbox(fail=True), get_settings())
    row = _rows(admin_url, appt)["appointment_booked"]
    assert row["status"] == "queued" and row["attempts"] == 1 and "mail server down" in row["detail"]
    assert row["send_after"] > datetime.now(UTC)
    with psycopg.connect(admin_url) as conn:
        conn.execute(
            "UPDATE notification_outbox SET attempts = %s, send_after = now()"
            " WHERE appt_id = %s AND kind = 'appointment_booked'",
            (MAX_ATTEMPTS - 1, appt),
        )
    await dispatch_due(pool, Outbox(fail=True), get_settings())
    assert _rows(admin_url, appt)["appointment_booked"]["status"] == "failed"


async def test_two_dispatchers_at_once_send_each_message_once(pool, world, admin_url):
    _confirm(admin_url, world)
    for _ in range(5):
        _book(admin_url, world)
    sender = Outbox()
    await asyncio.gather(*(dispatch_due(pool, sender, get_settings(), limit=3) for _ in range(4)))
    await dispatch_due(pool, sender, get_settings())
    subjects = [e.subject for e in sender.to(_email(world))]
    assert len(subjects) == 5


async def test_others_cannot_read_or_write_someone_elses_messages(pool, world, admin_url):
    _confirm(admin_url, world)
    _book(admin_url, world)
    stranger = {"user_id": str(uuid.uuid4()), "role": "patient", "acting_for_patient_id": str(uuid.uuid4())}
    assert await service.list_messages(pool, stranger) == []  # type: ignore[arg-type]
    mine = await service.list_messages(pool, _auth(world))
    assert {m["kind"] for m in mine} >= {"appointment_booked"}
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with scoped(pool, _auth(world)) as conn:
            await conn.execute(
                "INSERT INTO notification_outbox (patient_id, kind, send_after)"
                " VALUES (%s, 'appointment_booked', now())",
                (world["patient"],),
            )
    desk = {"user_id": str(uuid.uuid4()), "role": "desk", "acting_for_patient_id": None}
    seen_by_desk = await service.list_messages(pool, desk, limit=500)  # type: ignore[arg-type]
    assert seen_by_desk and all(m["patient_name"] for m in seen_by_desk)
