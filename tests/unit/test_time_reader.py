"""The model reads booking follow-ups the rules miss; code checks everything it returns."""

import asyncio
import re
from datetime import date

from services.agent.triage.time_reader import TimeForm, TimeRequestReader
from services.agent.triage.times import TimeRequest
from services.platform.egress.client import EgressChatClient

TODAY = date(2026, 11, 4)
OPTIONS = [
    {"doctor_id": "d-prasad", "doctor_name": "Prasad Jadhav", "clinic_name": "Baner Clinic"},
    {"doctor_id": "d-chetan", "doctor_name": "Chetan Ranade", "clinic_name": "Aundh Clinic"},
    {"doctor_id": "d-seema", "doctor_name": "Seema Srivastava", "clinic_name": "Camp Clinic"},
]


class FormChat:
    """Stands in for the egress client: returns a fixed form and records the request."""

    def __init__(self, form: TimeForm | None = None, error: Exception | None = None, delay: float = 0):
        self.form, self.error, self.delay, self.requests = form, error, delay, []

    async def ask_structured(self, request, schema):
        self.requests.append(request)
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.form


async def read(chat, text="does the lady doctor have anything after lunch?"):
    reader = TimeRequestReader(chat, deadline_seconds=0.2)  # type: ignore[arg-type]
    return await reader.read(text, options=OPTIONS, doctors=OPTIONS, today=TODAY)


async def test_doctor_words_are_matched_to_an_offered_doctor_by_code():
    form = TimeForm(wants_other_times=True, doctor_words="Seema", part_of_day="afternoon")
    assert await read(FormChat(form)) == TimeRequest("d-seema", None, "afternoon")


async def test_a_doctor_the_patient_was_not_offered_is_never_chosen():
    form = TimeForm(wants_other_times=True, doctor_words="Dr Mehta")
    assert await read(FormChat(form)) == TimeRequest(None, None, None)


async def test_pointing_at_an_option_by_position_or_clinic():
    assert await read(FormChat(TimeForm(wants_other_times=True, option=2))) == TimeRequest(
        "d-chetan", None, None
    )
    assert (await read(FormChat(TimeForm(wants_other_times=True, option=9)))).doctor_id is None


async def test_days_in_the_past_or_far_ahead_are_dropped():
    for bad in (date(2026, 11, 1), date(2027, 6, 1)):
        result = await read(FormChat(TimeForm(wants_other_times=True, day=bad)))
        assert result is not None and result.day is None
    good = await read(FormChat(TimeForm(wants_other_times=True, day=date(2026, 11, 6))))
    assert good is not None and good.day == date(2026, 11, 6)


async def test_not_a_time_request_or_a_failing_model_leaves_it_to_the_rules():
    assert await read(FormChat(TimeForm(wants_other_times=False))) is None
    assert await read(FormChat(error=RuntimeError("down"))) is None
    assert await read(FormChat(TimeForm(wants_other_times=True), delay=1)) is None  # past the deadline


async def test_the_model_sees_clinics_not_doctors_and_gets_todays_date():
    chat = FormChat(TimeForm(wants_other_times=False))
    await read(chat)
    prompt = chat.requests[0].user
    assert "Today is Wednesday 2026-11-04" in prompt
    assert "2: Aundh Clinic" in prompt
    assert not any(o["doctor_name"] in prompt for o in OPTIONS)


class EchoNameModel:
    """A chat model that copies back whatever stands for the doctor's name in the text it receives."""

    def __init__(self):
        self.seen = ""

    def with_structured_output(self, schema):
        outer = self

        class Structured:
            async def ainvoke(self, messages):
                outer.seen = messages[-1]["content"]
                patient = outer.seen.split("Patient:")[-1]
                token = re.search(r"<[A-Z_]+_\d+>", patient)
                return {"wants_other_times": True, "doctor_words": token.group(0) if token else None}

        return Structured()


async def test_through_the_real_egress_client_the_name_is_masked_out_and_matched_back():
    model = EchoNameModel()
    reader = TimeRequestReader(EgressChatClient(model))  # type: ignore[arg-type]
    result = await reader.read(
        "Can Dr Seema Srivastava see me on another day?", options=OPTIONS, doctors=OPTIONS, today=TODAY
    )
    assert "Seema" not in model.seen
    assert result == TimeRequest("d-seema", None, None)


async def test_asking_for_all_doctors_again():
    result = await read(FormChat(TimeForm(wants_other_times=True, all_doctors=True)))
    assert result == TimeRequest(None, None, None, True)
