"""Reading "other times" requests while a patient chooses an appointment."""

from datetime import date

import pytest

from services.agent.supervisor.graph import is_time_followup, rule_assign
from services.agent.triage.times import TimeRequest, describe_when, parse_time_request

DOCTORS = [
    {"doctor_id": "d-prasad", "doctor_name": "Prasad Jadhav"},
    {"doctor_id": "d-chetan", "doctor_name": "Chetan Ranade"},
    {"doctor_id": "d-seema", "doctor_name": "Seema Srivastava"},
]
WED = date(2026, 11, 4)  # a Wednesday


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Need other timing slots for chetan doctor", TimeRequest("d-chetan", None, None)),
        ("more times with Dr Ranade", TimeRequest("d-chetan", None, None)),
        ("anything tomorrow evening?", TimeRequest(None, date(2026, 11, 5), "evening")),
        ("kal subah Prasad ke saath?", TimeRequest("d-prasad", date(2026, 11, 5), "morning")),
        ("Can I see Seema instead?", TimeRequest("d-seema", None, None)),
        ("what about Monday?", TimeRequest(None, date(2026, 11, 9), None)),
        ("is there a slot on 12 Nov", TimeRequest(None, date(2026, 11, 12), None)),
        ("Nov 3rd afternoon", TimeRequest(None, date(2027, 11, 3), "afternoon")),  # past date: next year
        ("other timings", TimeRequest(None, None, None)),
        ("timings for seema", TimeRequest("d-seema", None, None)),
        ("seema slots", TimeRequest("d-seema", None, None)),
        ("parso shaam", TimeRequest(None, date(2026, 11, 6), "evening")),
    ],
)
def test_reads_doctor_day_and_part_of_day(text, expected):
    assert parse_time_request(text, DOCTORS, WED) == expected


@pytest.mark.parametrize("text", ["which doctor is it?", "what is the doctor specialization?", "thanks"])
def test_other_questions_are_not_time_requests(text):
    assert parse_time_request(text, DOCTORS, WED) is None


def test_an_ambiguous_name_names_nobody():
    two_ravis = [
        {"doctor_id": "a", "doctor_name": "Ravi Kumar"},
        {"doctor_id": "b", "doctor_name": "Ravi Shah"},
    ]
    assert parse_time_request("other times with Ravi", two_ravis, WED) == TimeRequest(None, None, None)


def test_describe_when():
    assert describe_when(date(2026, 11, 10), "evening") == "on Tue 10 Nov in the evening"
    assert describe_when(None, "morning") == "in the morning"
    assert describe_when(None, None) == ""


def test_time_followups_continue_the_booking_but_symptoms_start_a_new_triage():
    assert is_time_followup("Need other timing slots for chetan doctor")
    assert is_time_followup("anything tomorrow evening?")
    assert not is_time_followup("my knee pain is worse since yesterday morning")
    assert rule_assign(["other timings please"], "patient", has_transcript=False, has_conversation=True) == [
        (0, "visit")
    ]
