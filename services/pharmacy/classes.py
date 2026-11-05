"""Therapeutic classes for formulary ingredients: which medicines a doctor might consider instead.

Deliberately conservative: two medicines share a class only when one is a reasonable alternative to the
other for the same purpose. Aspirin and clopidogrel are both antiplatelets but are not interchangeable,
so they are separate; so are metformin and glimepiride, and the two antibiotics. The doctor always
decides; this only decides what is *listed*. Keyed by active ingredient, so it also applies to the brand
catalogue (the A-Z Medicine Dataset of India) by its composition. Pending clinical review.
"""

CLASS_BY_INGREDIENT: dict[str, str] = {
    "atorvastatin": "Statin",
    "rosuvastatin": "Statin",
    "metformin": "Biguanide (antidiabetic)",
    "glimepiride": "Sulfonylurea (antidiabetic)",
    "amlodipine": "Calcium channel blocker",
    "telmisartan": "Angiotensin receptor blocker",
    "losartan": "Angiotensin receptor blocker",
    "metoprolol": "Beta blocker",
    "aspirin": "Antiplatelet (aspirin)",
    "clopidogrel": "Antiplatelet (P2Y12 inhibitor)",
    "paracetamol": "Analgesic and antipyretic",
    "ibuprofen": "NSAID",
    "diclofenac": "NSAID",
    "pantoprazole": "Proton pump inhibitor",
    "omeprazole": "Proton pump inhibitor",
    "ondansetron": "Antiemetic",
    "cetirizine": "Antihistamine",
    "montelukast": "Leukotriene receptor antagonist",
    "salbutamol": "Short-acting bronchodilator",
    "azithromycin": "Macrolide antibiotic",
    "amoxicillin": "Penicillin antibiotic",
    "levothyroxine": "Thyroid hormone",
    "cholecalciferol": "Vitamin D",
    "vitamin d3": "Vitamin D",
    "calcium carbonate": "Calcium supplement",
    "ors": "Oral rehydration",
}


def class_for(name_or_composition: str) -> str | None:
    """The class of a single-ingredient medicine, from its name or the start of its composition."""
    text = name_or_composition.strip().lower()
    for ingredient in sorted(CLASS_BY_INGREDIENT, key=len, reverse=True):
        if text.startswith(ingredient):
            return CLASS_BY_INGREDIENT[ingredient]
    return None
