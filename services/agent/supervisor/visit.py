"""Answers about the appointment in this chat: deterministic, from the booking's saved facts.

No model writes these sentences. The supervisor's planner only decides that a message is a follow-up;
this module picks which facts the question asks for and states them. Nothing outside the booking can
appear in an answer, so nothing can be invented.

    answer_visit("what is the doctor specialization?", facts)
    -> "Chetan Ranade is an Orthopaedics specialist: bones, joints, muscles and injuries to them."
"""

import re
from dataclasses import dataclass

# What each specialty looks after, in plain words. A fixed, reviewable table: descriptive, never advice.
SPECIALTY_ABOUT: dict[str, str] = {
    "General Medicine": "common illnesses in adults, and the first doctor to see when you're unsure",
    "Paediatrics": "the health of babies, children and teenagers",
    "Obstetrics and Gynaecology": "pregnancy, childbirth and women's reproductive health",
    "Orthopaedics": "bones, joints, muscles and injuries to them",
    "Cardiology": "the heart and blood pressure",
    "Dermatology": "skin, hair and nails",
    "ENT": "the ear, nose and throat",
    "Ophthalmology": "the eyes and vision",
    "General Surgery": "operations on the abdomen, hernias and other common surgical problems",
    "Endocrinology": "hormones, including diabetes and thyroid conditions",
    "Gastroenterology": "the stomach, intestines and digestion",
    "Pulmonology": "the lungs and breathing",
    "Neurology": "the brain, nerves and conditions such as headaches and seizures",
    "Psychiatry": "mental health, including mood, anxiety and sleep problems",
    "Nephrology": "the kidneys",
    "Urology": "the urinary tract and the male reproductive system",
    "Dentistry": "teeth and gums",
    "Physiotherapy": "movement, exercise-based recovery and rehabilitation",
    "Rheumatology": "arthritis and other joint and autoimmune conditions",
    "Medical Oncology": "cancer treatment with medicines",
    "Surgical Oncology": "cancer treatment with surgery",
    "Haematology": "the blood",
    "Infectious Diseases": "infections that are severe, unusual or hard to treat",
    "Neurosurgery": "surgery on the brain, spine and nerves",
    "Cardiothoracic Surgery": "surgery on the heart and chest",
    "Plastic Surgery": "reconstructive surgery, including after injuries and burns",
    "Vascular Surgery": "surgery on the arteries and veins",
    "Paediatric Surgery": "surgery for babies and children",
    "Neonatology": "newborn babies, especially those born early or unwell",
    "Geriatric Medicine": "the health of older adults",
    "Allergy and Immunology": "allergies and the immune system",
    "Hepatology": "the liver",
    "Pain Medicine": "long-lasting pain",
    "Sleep Medicine": "sleep problems",
    "Sports Medicine": "sports injuries and staying active safely",
    "Nutrition and Dietetics": "food, diet and nutrition",
    "Clinical Psychology": "talking therapies for emotional and mental health",
    "Bariatric Surgery": "weight-loss surgery",
}


@dataclass(frozen=True)
class VisitFacts:
    doctor: str
    specialty: str | None
    clinic: str
    time: str  # as the patient reads it, e.g. "Mon 9 Nov, 09:00"
    reference: str | None  # None until booked


# What a question can ask for. English and romanised Hindi; order is the order answers are given in.
_ASKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "specialty",
        re.compile(
            r"\bspe[cs]+[ia]*l\w*|kind of doctor|type of doctor"  # specialist, specilization, speciality
            r"|what (?:does|do) (?:he|she|they|the doctor) (?:do|treat)|department"
            r"|kis (?:cheez|chiz|bimari) ka",
            re.I,
        ),
    ),
    (
        "doctor",
        re.compile(
            r"\bwho\b|which doctor|doctor'?s? name|name of the doctor|kaun(?:se|sa|si)? doctor|kaun hai", re.I
        ),
    ),
    ("time", re.compile(r"\bwhen\b|what time|\btime\b|\bdate\b|which day|\bkab\b|kitne baje", re.I)),
    ("place", re.compile(r"\bwhere\b|clinic|address|hospital|location|\bkahan\b|kidhar", re.I)),
    ("reference", re.compile(r"reference|booking (?:id|number)|confirmation", re.I)),
)


def asked_for(question: str) -> list[str]:
    return [name for name, pattern in _ASKS if pattern.search(question)]


def answer_visit(question: str, facts: VisitFacts) -> str:
    """The facts the question asks for, in plain sentences; the full summary if it asks for none."""
    parts: list[str] = []
    asks = asked_for(question)
    if "specialty" in asks and facts.specialty:
        about = SPECIALTY_ABOUT.get(facts.specialty)
        article = "an" if facts.specialty[0].lower() in "aeiou" else "a"
        parts.append(
            f"{facts.doctor} is {article} {facts.specialty} specialist" + (f": {about}." if about else ".")
        )
    elif "doctor" in asks:
        parts.append(f"Your doctor is {facts.doctor}" + (f", {facts.specialty}." if facts.specialty else "."))
    if "time" in asks:
        parts.append(f"{'Your appointment is' if facts.reference else 'The slot is'} on {facts.time} IST.")
    if "place" in asks:
        parts.append(f"It's at {facts.clinic}.")
    if "reference" in asks and facts.reference:
        parts.append(f"Your booking reference is {facts.reference}.")
    if parts:
        return " ".join(parts)
    return (
        f"Your appointment is with {facts.doctor}"
        + (f", {facts.specialty}" if facts.specialty else "")
        + f", at {facts.clinic} on {facts.time} IST."
        + (f" Booking reference {facts.reference}." if facts.reference else "")
    )
