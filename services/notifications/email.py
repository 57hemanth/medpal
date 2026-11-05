"""Email senders behind one small interface. Development logs or uses Mailpit; production uses SMTP."""

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Protocol

from services.platform.config import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str
    html: str


class EmailSender(Protocol):
    async def send(self, email: Email) -> None: ...


def mask_email(address: str) -> str:
    """'asha.verma@example.com' -> 'as•••@example.com': enough to recognise, not to copy."""
    local, _, domain = address.partition("@")
    return f"{local[:2]}•••@{domain}"


class LogEmailSender:
    """Development only: records that a message would have gone, never its body (it names the patient)."""

    async def send(self, email: Email) -> None:
        log.warning("email to %s: %s", mask_email(email.to), email.subject)


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _send_blocking(self, email: Email) -> None:
        s = self._settings
        message = EmailMessage()
        message["From"] = s.email_from
        message["To"] = email.to
        message["Subject"] = email.subject
        message["Message-ID"] = make_msgid(domain="medpal")
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_username and s.smtp_password:
                smtp.login(s.smtp_username, s.smtp_password)
            smtp.send_message(message)

    async def send(self, email: Email) -> None:
        # smtplib blocks; keep it off the event loop.
        await asyncio.to_thread(self._send_blocking, email)


def build_email_sender(settings: Settings) -> EmailSender:
    return SmtpEmailSender(settings) if settings.email_provider == "smtp" else LogEmailSender()
