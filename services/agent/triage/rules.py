"""Versioned draft rules for triage safety and specialty routing.

These rules are engineering defaults, not clinician-approved medical content.
The version/status travel with graph state so clients can display that clearly.
"""

from dataclasses import dataclass

RULESET_VERSION = "triage-draft-2026-11-02"
RULESET_STATUS = "draft"
SPECIALTY_CONFIDENCE_THRESHOLD = 0.72


@dataclass(frozen=True)
class PhraseRule:
    rule_id: str
    phrases: tuple[str, ...]
    locale: str
    status: str = RULESET_STATUS
    provenance: str = "engineering-draft"


RED_FLAG_RULES: tuple[PhraseRule, ...] = (
    PhraseRule("redflag_chest_pain", ("chest pain", "chest tightness", "seene mein dard"), "en+hi-Latn"),
    PhraseRule("redflag_breathing", ("breathless", "can't breathe", "saans lene mein takleef"), "en+hi-Latn"),
    PhraseRule("redflag_unconscious", ("unconscious", "fainted"), "en"),
    PhraseRule("redflag_stroke", ("slurred speech", "face drooping"), "en"),
    PhraseRule("redflag_self_harm", ("suicide", "self harm", "kill myself"), "en"),
)

SPECIALTY_RULES: tuple[PhraseRule, ...] = (
    PhraseRule("specialty_orthopaedics", ("knee", "back pain", "fracture", "joint", "shoulder"), "en"),
    PhraseRule("specialty_cardiology", ("palpitation", "heart", "high bp", "blood pressure"), "en"),
    PhraseRule("specialty_dermatology", ("rash", "skin", "itching", "acne"), "en"),
    PhraseRule("specialty_ent", ("ear pain", "sore throat", "sinus", "hearing"), "en"),
    PhraseRule("specialty_pulmonology", ("cough", "wheezing", "asthma"), "en"),
    PhraseRule("specialty_gastroenterology", ("stomach", "vomiting", "loose motion", "acidity"), "en"),
    PhraseRule("specialty_neurology", ("migraine", "seizure", "numbness", "headache"), "en"),
    PhraseRule(
        "specialty_general_medicine", ("fever", "body ache", "fatigue", "bukhar", "khansi"), "en+hi-Latn"
    ),
)

SPECIALTY_BY_RULE_ID = {
    "specialty_orthopaedics": "Orthopaedics",
    "specialty_cardiology": "Cardiology",
    "specialty_dermatology": "Dermatology",
    "specialty_ent": "ENT",
    "specialty_pulmonology": "Pulmonology",
    "specialty_gastroenterology": "Gastroenterology",
    "specialty_neurology": "Neurology",
    "specialty_general_medicine": "General Medicine",
}


@dataclass(frozen=True)
class SpecialtyMatch:
    specialty: str
    confidence: float
    rule_id: str
    needs_clarification: bool = False


def match_red_flags(text: str) -> list[str]:
    lowered = text.lower()
    return sorted(
        rule.rule_id for rule in RED_FLAG_RULES if any(phrase in lowered for phrase in rule.phrases)
    )


def match_specialty(text: str) -> SpecialtyMatch:
    lowered = text.lower()
    for rule in SPECIALTY_RULES:
        if any(phrase in lowered for phrase in rule.phrases):
            return SpecialtyMatch(SPECIALTY_BY_RULE_ID[rule.rule_id], 0.9, rule.rule_id)
    return SpecialtyMatch(
        specialty="General Medicine",
        confidence=0.55,
        rule_id="specialty_uncertain_default",
        needs_clarification=True,
    )
