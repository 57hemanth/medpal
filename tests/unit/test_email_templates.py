"""Appointment email wording: fixed, local time, nothing clinical, safe in HTML."""

from datetime import UTC, datetime

import pytest

from services.notifications.email import mask_email
from services.notifications.templates import Visit, appointment_email
from services.platform.config import Settings

VISIT = Visit(
    "Asha Verma", "Nikhil Patel", "Hinjewadi Clinic", "Pune", datetime(2026, 11, 9, 9, 45, tzinfo=UTC)
)


@pytest.mark.parametrize(
    ("kind", "subject"),
    [
        ("appointment_booked", "Appointment confirmed: Mon 9 Nov, 15:15"),
        ("appointment_reminder_24h", "Reminder: your appointment tomorrow, Mon 9 Nov, 15:15"),
        ("appointment_reminder_2h", "Reminder: your appointment in about 2 hours, Mon 9 Nov, 15:15"),
        ("appointment_cancelled", "Appointment cancelled: Mon 9 Nov, 15:15"),
    ],
)
def test_each_message_says_who_where_and_when_in_clinic_time(kind, subject):
    mail = appointment_email(kind, VISIT, to="asha@example.com", base_url="https://medpal.example")
    assert mail.subject == subject  # 09:45 UTC is 15:15 in India
    assert (
        "Hello Asha," in mail.text
        and "Dr. Nikhil Patel" in mail.text
        and "Hinjewadi Clinic, Pune" in mail.text
    )
    assert "Monday 9 November at 15:15" in mail.text
    assert "https://medpal.example/appointments" in mail.html
    assert "Verma" not in mail.text  # first name only


def test_names_are_escaped_in_html():
    visit = Visit("<b>Eve</b>", "<script>x</script>", "Clinic & Co", None, VISIT.starts_at)
    mail = appointment_email("appointment_booked", visit, to="e@example.com", base_url="http://x")
    assert "<script>" not in mail.html and "&lt;script&gt;" in mail.html
    assert "Clinic &amp; Co" in mail.html


def test_addresses_are_masked_for_records():
    assert mask_email("asha.verma@example.com") == "as•••@example.com"


def test_production_refuses_to_log_emails_instead_of_sending_them():
    prod = {"env": "prod", "auth_mode": "oidc", "chat_provider": "openai", "object_store_backend": "s3"}
    prod["notify_dispatch"] = "inline"  # the test suite turns sending off by default
    with pytest.raises(ValueError, match="real email provider"):
        Settings(_env_file=None, **prod)
    assert Settings(_env_file=None, **prod, email_provider="smtp").email_provider == "smtp"
    assert Settings(_env_file=None, **{**prod, "notify_dispatch": "off"}).notify_dispatch == "off"
