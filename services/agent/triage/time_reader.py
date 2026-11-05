"""The model reads a booking follow-up the rules couldn't: "does the lady doctor have anything after lunch?",
"the Aundh one, but later in the week", "Seema ke paas Friday ko kuch hai?".

The model fills in a form; code decides what the form means:
* **doctor**: the model never sees or returns a doctor's identity. Names are masked before the call
  (egress client), so it returns the words the patient used ("Seema", "the second one") and the option
  number they point at; code maps those words back and accepts only a doctor already offered here;
* **day**: an ISO date, accepted only from today to 60 days ahead;
* **part of day**: one of morning, afternoon, evening.
Nothing it writes is shown to the patient. Slow, down or malformed: the patient gets the rules' answer.
"""

import asyncio
import logging
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from services.platform.egress.client import EgressChatClient, ModelRequest

from .times import TimeRequest, match_doctor

log = logging.getLogger(__name__)

MAX_DAYS_AHEAD = 60

SYSTEM = (
    "You read one message from a patient who is choosing an appointment from a list of options. "
    "Decide whether they are asking to see other appointment times (a different doctor from the list, "
    "day, or time of day). If they are, fill in: doctor_words, the exact words they used for the doctor "
    "(a name or part of one, copied as written), or null; option, the option number they mean when they "
    'point at one by position or clinic ("the second one", "the Aundh one"), or null; day, the date '
    "they ask for as YYYY-MM-DD, or null; part_of_day: morning (before 12), afternoon (12 to 5 pm, "
    '"after lunch"), evening (after 5 pm), or null; all_doctors, true when they want to see the other '
    "doctors again rather than one doctor. Never guess a value the message does not give."
)


class TimeForm(BaseModel):
    wants_other_times: bool
    doctor_words: str | None = Field(default=None, max_length=80)
    option: int | None = Field(default=None, ge=1, le=20)
    day: date | None = None
    part_of_day: Literal["morning", "afternoon", "evening"] | None = None
    all_doctors: bool = False


class TimeRequestReader:
    def __init__(self, chat: EgressChatClient, *, deadline_seconds: float = 4.0) -> None:
        self._chat = chat
        self._deadline = deadline_seconds

    async def read(
        self,
        text: str,
        *,
        options: list[dict[str, str]],
        doctors: list[dict[str, str]],
        today: date,
    ) -> TimeRequest | None:
        """`options` are the cards on screen (doctor_id, clinic_name), in order; `doctors` every doctor
        offered in this chat. Returns None when it isn't a time request or the model can't say."""
        listed = "\n".join(f"{i}: {o['clinic_name']}" for i, o in enumerate(options, start=1))
        try:
            form = await asyncio.wait_for(
                self._chat.ask_structured(
                    ModelRequest(
                        system=SYSTEM,
                        user=f"Today is {today:%A} {today.isoformat()}.\nOptions on screen (by clinic):\n"
                        f"{listed}\n\nPatient: {text}",
                        purpose="booking follow-up",
                        tier="small",
                    ),
                    TimeForm,
                ),
                timeout=self._deadline,
            )
        except Exception as exc:  # noqa: BLE001  timeout, provider down, invalid output: rules decide
            log.info("time request reader skipped: %s", type(exc).__name__)
            return None
        if not form.wants_other_times:
            return None
        doctor_id = match_doctor(form.doctor_words or "", doctors) if form.doctor_words else None
        if doctor_id is None and form.option and form.option <= len(options):
            doctor_id = options[form.option - 1]["doctor_id"]
        day = form.day if form.day and today <= form.day <= today + timedelta(days=MAX_DAYS_AHEAD) else None
        return TimeRequest(
            doctor_id=doctor_id,
            day=day,
            part_of_day=form.part_of_day,
            all_doctors=form.all_doctors and doctor_id is None,
        )
