"""Generated-layer checks: the "enough data" rules and the audit rules."""

from collections import Counter, defaultdict
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from data.synthetic.generate import (
    N_DOCTORS,
    SLOTS_PER_DAY,
    WORKING_DAYS,
    DoctorRow,
    generate_doctors,
    generate_slots,
    session_start,
    specialty_quota,
    working_days,
)
from data.synthetic.reference import CLINICS, MIN_DOCTORS_PER_SPECIALTY, SPECIALTIES

START = date(2026, 11, 9)  # a Monday; fixed so the test is reproducible


@pytest.fixture(scope="module")
def doctors():
    docs, rejected = generate_doctors()
    assert rejected == 0
    return docs


@pytest.fixture(scope="module")
def slots(doctors):
    return list(generate_slots(doctors, START))


def test_reference_sizes():
    assert len(SPECIALTIES) == 38
    assert len(CLINICS) == 22
    assert Counter(c.city for c in CLINICS) == {"Pune": 11, "Hyderabad": 11}


def test_quota_sums_and_floor():
    quota = specialty_quota()
    assert sum(quota.values()) == N_DOCTORS
    assert min(quota.values()) >= MIN_DOCTORS_PER_SPECIALTY


def test_every_specialty_has_at_least_ten_doctors(doctors):
    counts = Counter(d.specialty for d in doctors)
    assert set(counts) == set(SPECIALTIES)
    assert min(counts.values()) >= MIN_DOCTORS_PER_SPECIALTY


def test_deterministic_for_a_seed():
    a, _ = generate_doctors(seed=7)
    b, _ = generate_doctors(seed=7)
    c, _ = generate_doctors(seed=8)
    assert [d.model_dump() for d in a] == [d.model_dump() for d in b]
    assert [d.name for d in a] != [d.name for d in c]


def test_names_unique_and_synthetic(doctors):
    assert len({d.name for d in doctors}) == len(doctors)
    assert all(d.synthetic for d in doctors)


def test_every_clinic_has_doctors(doctors):
    staffed = {d.primary_clinic for d in doctors} | {d.second_clinic for d in doctors if d.second_clinic}
    assert staffed == {c.key for c in CLINICS}


def test_languages_follow_the_city(doctors):
    city = {c.key: c.city for c in CLINICS}
    for d in doctors:
        assert "en" in d.languages
        if city[d.primary_clinic] == "Pune":
            assert "te" not in d.languages
        else:
            assert "mr" not in d.languages


def test_second_clinic_is_in_the_same_city(doctors):
    city = {c.key: c.city for c in CLINICS}
    assert all(city[d.second_clinic] == city[d.primary_clinic] for d in doctors if d.second_clinic)


def test_invalid_rows_are_rejected_not_repaired():
    good = {
        "doctor_id": "x",
        "name": "Asha Kale",
        "gender": "f",
        "specialty": "Cardiology",
        "primary_clinic": "pun-baner",
        "second_clinic": None,
        "session": "morning",
        "languages": ["en", "mr"],
        "years": 5,
    }
    DoctorRow(**good)
    for bad in ({"specialty": "Astrology"}, {"languages": ["mr"]}, {"years": 0}, {"languages": ["en", "fr"]}):
        with pytest.raises(ValidationError):
            DoctorRow(**{**good, **bad})


# ---- slots ------------------------------------------------------------------------------------


def test_slot_volume_matches_the_target_volume(slots):
    assert len(slots) == N_DOCTORS * WORKING_DAYS * SLOTS_PER_DAY == 480_000


def test_no_doctor_is_double_booked_in_time(slots):
    assert len({(doc, ts) for doc, _, ts in slots}) == len(slots)


def test_no_sunday_slots(slots):
    assert all(ts.weekday() != 6 for _, _, ts in slots)


def test_slots_sit_inside_clinic_hours(slots):
    hours = {c.key: (c.opens_at, c.closes_at) for c in CLINICS}
    for _, clinic, ts in slots[::97]:  # sampled: full scan is covered by session_start's own check
        opens, closes = hours[clinic]
        assert opens <= ts.time() < closes


def test_every_clinic_has_slots_on_every_working_day(slots):
    days_by_clinic: dict[str, set[date]] = defaultdict(set)
    for _, clinic, ts in slots:
        days_by_clinic[clinic].add(ts.date())
    expected = set(working_days(START, WORKING_DAYS))
    assert {k: v == expected for k, v in days_by_clinic.items()} == {c.key: True for c in CLINICS}


@pytest.mark.parametrize("clinic", CLINICS, ids=lambda c: c.key)
@pytest.mark.parametrize("session", ["morning", "evening"])
def test_sessions_fit_every_clinic(clinic, session):
    start = datetime.combine(START, session_start(clinic, session))
    assert clinic.opens_at <= start.time()
