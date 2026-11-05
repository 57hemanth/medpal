"""Fixed wording for every message. No model text, no symptoms, no specialty (it can reveal a condition):
only who, where and when, and how to change it."""

from dataclasses import dataclass
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from services.notifications.email import Email

CLINIC_TZ = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class Visit:
    patient_name: str
    doctor_name: str
    clinic_name: str
    city: str | None
    starts_at: datetime


def when(starts_at: datetime) -> str:
    local = starts_at.astimezone(CLINIC_TZ)
    return f"{local:%A} {local.day} {local:%B} at {local:%H:%M}"


def short_when(starts_at: datetime) -> str:
    local = starts_at.astimezone(CLINIC_TZ)
    return f"{local:%a} {local.day} {local:%b}, {local:%H:%M}"


def _doctor(name: str) -> str:
    return name if name.lower().startswith("dr") else f"Dr. {name}"


def _first_name(name: str) -> str:
    return name.split()[0] if name.strip() else "there"


def _place(visit: Visit) -> str:
    return f"{visit.clinic_name}, {visit.city}" if visit.city else visit.clinic_name


def _html(paragraphs: list[str], link: tuple[str, str], footer: str) -> str:
    body = "".join(f'<p style="margin:0 0 14px">{p}</p>' for p in paragraphs)
    label, url = link
    return (
        '<div style="font-family:Arial,sans-serif;font-size:15px;line-height:1.55;'
        'color:#1f2a27;max-width:520px">'
        '<p style="margin:0 0 18px;font-weight:bold;color:#14532d">MedPal</p>'
        f"{body}"
        f'<p style="margin:20px 0"><a href="{escape(url)}" style="background:#1d6b52;color:#fff;'
        f'padding:10px 16px;border-radius:8px;text-decoration:none">{escape(label)}</a></p>'
        f'<p style="margin:24px 0 0;font-size:12px;color:#6b7a75">{footer}</p></div>'
    )


def appointment_email(kind: str, visit: Visit, *, to: str, base_url: str) -> Email:
    hello = f"Hello {_first_name(visit.patient_name)},"
    who, where, at = _doctor(visit.doctor_name), _place(visit), when(visit.starts_at)
    manage = f"{base_url}/appointments"
    settings = f"{base_url}/settings"
    footer_text = (
        f"You get these emails because appointment emails are on in MedPal. Turn them off: {settings}"
    )
    footer_html = (
        "You get these emails because appointment emails are on in MedPal. "
        f'<a href="{escape(settings)}" style="color:#6b7a75">Turn them off</a>.'
    )
    if kind == "appointment_booked":
        subject = f"Appointment confirmed: {short_when(visit.starts_at)}"
        lines = [
            hello,
            f"Your appointment with {who} at {where} is booked for {at}.",
            "Please arrive 10 minutes early. If you can't make it, cancel so someone else can have the time.",
        ]
    elif kind in ("appointment_reminder_24h", "appointment_reminder_2h"):
        soon = "tomorrow" if kind.endswith("24h") else "in about 2 hours"
        subject = f"Reminder: your appointment {soon}, {short_when(visit.starts_at)}"
        lines = [
            hello,
            f"A reminder that you see {who} at {where} {soon}, on {at}.",
            "If you can't make it, please cancel so someone else can have the time.",
        ]
    elif kind == "appointment_cancelled":
        subject = f"Appointment cancelled: {short_when(visit.starts_at)}"
        lines = [
            hello,
            f"Your appointment with {who} at {where} on {at} has been cancelled.",
            "If you didn't ask for this, or want another time, book again in MedPal.",
        ]
    else:
        raise ValueError(f"no template for {kind}")
    link = ("Manage appointments", manage)
    text = "\n\n".join([*lines, f"{link[0]}: {manage}", footer_text]) + "\n"
    return Email(to=to, subject=subject, text=text, html=_html([escape(x) for x in lines], link, footer_html))


def verification_email(patient_name: str, *, to: str, link: str) -> Email:
    lines = [
        f"Hello {_first_name(patient_name)},",
        "Confirm this address to get appointment confirmations and reminders from MedPal.",
        "The link works for 24 hours. If you didn't ask for this, ignore this email.",
    ]
    text = "\n\n".join([*lines, f"Confirm email: {link}"]) + "\n"
    return Email(
        to=to,
        subject="Confirm your email for MedPal",
        text=text,
        html=_html([escape(x) for x in lines], ("Confirm email", link), "MedPal appointment emails"),
    )
