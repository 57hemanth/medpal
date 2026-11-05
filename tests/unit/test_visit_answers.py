"""Booking follow-ups are answered by code from the booking's facts: the question decides which facts."""

import pytest

from data.synthetic.reference import SPECIALTIES
from services.agent.supervisor.visit import SPECIALTY_ABOUT, VisitFacts, answer_visit

FACTS = VisitFacts("Chetan Ranade", "Orthopaedics", "Aundh Clinic", "Mon 9 Nov, 09:00", "145BA205")


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "What is doctor specilization?",  # typo as a patient typed it
            "Chetan Ranade is an Orthopaedics specialist: bones, joints, muscles and injuries to them.",
        ),
        ("what kind of doctor is he?", "Chetan Ranade is an Orthopaedics specialist"),
        (
            "kaunse doctor hai aur kab hai?",
            "Your doctor is Chetan Ranade, Orthopaedics. Your appointment is on",
        ),
        ("Which clinic is it at?", "It's at Aundh Clinic."),
        ("what's my booking reference", "Your booking reference is 145BA205."),
        ("please be specific about the time", "Your appointment is on Mon 9 Nov, 09:00 IST."),
        ("tell me about it", "Your appointment is with Chetan Ranade, Orthopaedics, at Aundh Clinic"),
    ],
)
def test_the_answer_states_what_was_asked(question, expected):
    assert answer_visit(question, FACTS).startswith(expected)


def test_answers_contain_only_the_bookings_facts():
    text = answer_visit("who, when, where and what specialty?", FACTS)
    for fact in ("Chetan Ranade", "Orthopaedics", "Aundh Clinic", "Mon 9 Nov, 09:00"):
        assert fact in text


def test_every_specialty_in_the_network_has_a_plain_description():
    names = {getattr(s, "name", s) for s in SPECIALTIES}
    assert names <= set(SPECIALTY_ABOUT)
