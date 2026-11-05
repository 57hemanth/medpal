"""Reading "other times" requests while the patient is choosing an appointment.

"Need other timing slots for Chetan", "anything tomorrow evening?", "kal shaam ko?", "Wednesday with
Dr Seema". Deterministic: the doctor must be one already offered in this chat, the day and part of the
day come from a small vocabulary, and anything else is left unset. No model reads or writes these.

    parse_time_request("other times for chetan", doctors, today)
    -> TimeRequest(doctor_id="…", day=None, part_of_day=None)
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

PartOfDay = Literal["morning", "afternoon", "evening"]

# Hours (clinic local time) each part of the day covers: [start, end).
PART_HOURS: dict[str, tuple[int, int]] = {"morning": (0, 12), "afternoon": (12, 17), "evening": (17, 24)}

_TIME_WORDS = re.compile(
    r"\b(?:times?|timings?|slots?|availability|available|schedule|later|earlier|another day|other day|"
    r"different day|reschedule|samay|waqt|time slot)\b",
    re.I,
)
_OTHER = re.compile(
    r"\b(?:other|another|more|different|next|later|earlier|else|any|anything|instead|dusra|dusre|aur)\b",
    re.I,
)
_PARTS: tuple[tuple[PartOfDay, re.Pattern[str]], ...] = (
    ("morning", re.compile(r"\b(?:morning|subah|suba)\b", re.I)),
    ("afternoon", re.compile(r"\b(?:afternoon|dopahar|dopehar|noon|after lunch|lunch ke baad)\b", re.I)),
    ("evening", re.compile(r"\b(?:evening|night|after work|shaam|sham)\b", re.I)),
)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WEEKDAY = re.compile(r"\b(" + "|".join(d[:3] for d in _WEEKDAYS) + r")[a-z]*\b", re.I)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MONTH = "(" + "|".join(_MONTHS) + r")[a-z]*"
_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH + r"\b", re.I)
_MONTH_DAY = re.compile(r"\b" + _MONTH + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)
_ALL_DOCTORS = re.compile(
    r"\b(?:other|different|all|another|any other|more) doctors?\b|\bkisi aur doctor\b|\bdusre doctor", re.I
)
_TITLES = re.compile(r"\b(?:dr|doctor|daktar)\.?\s*", re.I)


@dataclass(frozen=True)
class TimeRequest:
    doctor_id: str | None
    day: date | None
    part_of_day: PartOfDay | None
    all_doctors: bool = False  # "show me the other doctors": every doctor's soonest again

    def merged(self, fallback: "TimeRequest | None") -> "TimeRequest":
        """Fill what this request left blank from `fallback`."""
        if fallback is None:
            return self
        return TimeRequest(
            doctor_id=self.doctor_id or fallback.doctor_id,
            day=self.day or fallback.day,
            part_of_day=self.part_of_day or fallback.part_of_day,
            all_doctors=self.all_doctors or fallback.all_doctors,
        )

    def as_resume(self) -> dict[str, str | None]:
        return {
            "doctor_id": self.doctor_id,
            "day": self.day.isoformat() if self.day else None,
            "part_of_day": self.part_of_day,
        }


def _day(text: str, today: date) -> date | None:
    lowered = text.lower()
    if re.search(r"\b(?:day after tomorrow|parso|parson)\b", lowered):
        return today + timedelta(days=2)
    if re.search(r"\b(?:tomorrow|tmrw|tmr|kal)\b", lowered):
        return today + timedelta(days=1)
    if re.search(r"\b(?:today|aaj)\b", lowered):
        return today
    if re.search(r"\bnext week\b", lowered):
        return today + timedelta(days=7 - today.weekday())  # the coming Monday
    for pattern, day_group, month_group in ((_DAY_MONTH, 1, 2), (_MONTH_DAY, 2, 1)):
        found = pattern.search(text)
        if found:
            month = _MONTHS.index(found.group(month_group).lower()[:3]) + 1
            try:
                when = date(today.year, month, int(found.group(day_group)))
            except ValueError:
                return None
            return when if when >= today else date(today.year + 1, month, when.day)
    found = re.search(r"\bthe (\d{1,2})(?:st|nd|rd|th)\b", lowered)  # "on the 12th": this month or next
    if found:
        try:
            when = today.replace(day=int(found.group(1)))
        except ValueError:
            return None
        if when < today:
            year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
            try:
                when = date(year, month, int(found.group(1)))
            except ValueError:
                return None
        return when
    found = _WEEKDAY.search(text)
    if found:
        target = [d[:3] for d in _WEEKDAYS].index(found.group(1).lower())
        return today + timedelta(days=(target - today.weekday()) % 7)
    return None


def match_doctor(text: str, doctors: list[dict[str, str]]) -> str | None:
    """A doctor offered in this chat, named by full, first or last name ("Chetan", "Dr Ranade")."""
    words = set(re.findall(r"[a-z]+", _TITLES.sub(" ", text.lower())))
    matches = []
    for doctor in doctors:
        names = [n for n in re.findall(r"[a-z]+", doctor["doctor_name"].lower()) if len(n) > 2]
        if names and any(n in words for n in names):
            matches.append(doctor["doctor_id"])
    return matches[0] if len(set(matches)) == 1 else None


def asks_other_times(text: str) -> bool:
    """Is this message asking for a different time, day or doctor? (The caller rules out symptoms.)"""
    names_when = bool(_day(text, date(2000, 1, 3))) or any(p.search(text) for _, p in _PARTS)
    return (
        names_when
        or bool(_ALL_DOCTORS.search(text))
        or bool(_TIME_WORDS.search(text) and _OTHER.search(text))
    )


def parse_time_request(text: str, doctors: list[dict[str, str]], today: date) -> TimeRequest | None:
    """The time request in `text`, or None if it isn't one. `doctors` are those offered in this chat."""
    doctor_id = match_doctor(text, doctors)
    day = _day(text, today)
    part = next((name for name, pattern in _PARTS if pattern.search(text)), None)
    # "Can I see Prasad instead?" asks for that doctor's times too.
    # "timings for seema" names an offered doctor and asks about times: enough on its own.
    if not asks_other_times(text) and not (doctor_id and (_OTHER.search(text) or _TIME_WORDS.search(text))):
        return None
    return TimeRequest(
        doctor_id=doctor_id,
        day=day,
        part_of_day=part,
        all_doctors=bool(_ALL_DOCTORS.search(text)) and not doctor_id,
    )


def describe_when(day: date | None, part_of_day: str | None) -> str:
    """'on Tue 10 Nov', 'in the evening', 'on Tue 10 Nov in the evening'."""
    bits = []
    if day:
        bits.append(f"on {day:%a} {day.day} {day:%b}")
    if part_of_day:
        bits.append(f"in the {part_of_day}")
    return " ".join(bits)
