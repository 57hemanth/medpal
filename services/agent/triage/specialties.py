"""The outpatient specialties MedPal books into, and what each looks after in plain words.

One list for every component: the specialty matcher (rules and model) may only choose from it, and the
assistant uses the descriptions when a patient asks what kind of doctor they're seeing. It must equal
the specialty table in the generated network (checked by a unit test).
"""

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

SPECIALTIES: tuple[str, ...] = tuple(SPECIALTY_ABOUT)
_BY_LOWER = {name.lower(): name for name in SPECIALTIES}


def canonical_specialty(name: object) -> str | None:
    """The exact specialty name for a model's answer, or None if it isn't one we book into."""
    return _BY_LOWER.get(str(name).strip().lower()) if name else None
