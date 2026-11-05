"""Versioned draft rules for triage safety and specialty routing.

These rules are engineering defaults, not clinician-approved medical content.
The version/status travel with graph state so clients can display that clearly.
"""

import re
from dataclasses import dataclass

RULESET_VERSION = "triage-draft-2026-11-03.3"  # .3: concept-near-severity patterns, held-out measured
RULESET_STATUS = "draft"
SPECIALTY_CONFIDENCE_THRESHOLD = 0.72


@dataclass(frozen=True)
class PhraseRule:
    rule_id: str
    phrases: tuple[str, ...]
    locale: str
    status: str = RULESET_STATUS
    provenance: str = "engineering-draft"


# Red-flag patterns are regular expressions over lowercased text, each anchored at a word start.
# Exact phrases do not generalise: on a held-out set of new phrasings they caught 3 of 30 emergencies.
# So each rule matches a CONCEPT (a body part or function) NEAR a SEVERITY term, in either order and
# within a few words, plus explicit event phrases. Measured against evals/sets/ for recall AND over-triage.
_OWNER = r"(?:my|the|his|her|their)\s+"


def _near(a: str, b: str, words: int = 6) -> str:
    """`a` and `b` within `words` words of each other, either order, same sentence."""
    gap = rf"(?:[^\w.!?]+\w+){{0,{words}}}[^\w.!?]+"
    return rf"(?:(?:{a})\w*{gap}(?:{b})|(?:{b})\w*{gap}(?:{a}))"


_CHEST = r"chest|seen[ae]y?|chhati|chaati|heart"
_CHEST_SEVERE = (
    r"pain|dard|ache|hurt|tight|heav|pressure|squeez|burn|crush|sitting\s+on|clutch|radiat|attack|discomfort"
)
_BREATH = r"breath|breathe|breathing|saans|sans"
_BREATH_SEVERE = (
    r"hard|difficult|struggl|can'?t|cannot|unable|catch|short|stop|rukk?|ruk|nahi|blue|fast|gasp|trouble"
    r"|problem|takleef|dikkat|phool"
)

RED_FLAG_RULES: tuple[PhraseRule, ...] = (
    PhraseRule(
        "redflag_chest_pain",
        (
            _near(_CHEST, _CHEST_SEVERE),
            r"(?:tight|heavy|crushing|sharp)\s+chest",
        ),
        "en+hi-Latn",
    ),
    PhraseRule(
        "redflag_breathing",
        (
            r"breathless",
            _near(_BREATH, _BREATH_SEVERE, 5),
            r"choking",
            r"gasping",
            r"(?:lips?|face|skin)\s+(?:look\s+|are\s+|is\s+|turning\s+)?blue|turning\s+blue",
        ),
        "en+hi-Latn",
    ),
    PhraseRule(
        "redflag_unconscious",
        (
            r"unconscious",
            r"lost\s+consciousness",
            r"black(?:ed)?\s+out",
            r"faint",
            r"passed\s+out",
            r"collapsed",
            r"(?:not|isn'?t|is\s+not|wasn'?t)\s+(?:waking|respond)",
            r"unresponsive",
            r"behosh",
            r"seizure",
            r"convuls",
            r"fits\b",
            r"gir\s+(?:gay[ae]|padd?[ae])",
        ),
        "en+hi-Latn",
    ),
    PhraseRule(
        "redflag_stroke",
        (
            r"slurred",
            _near(r"face|mouth|lips?|smile", r"droop|twist|crooked|uneven|slant", 4),
            r"(?:can'?t|cannot|unable\s+to)\s+speak",
            _near(r"one\s+side|left\s+side|right\s+side", r"weak|numb|paraly|went\s+numb", 5),
            rf"can'?t\s+(?:lift|move)\s+(?:{_OWNER})?(?:arm|leg)",
            r"(?:lost|loss\s+of)\s+(?:\w+\s+)?(?:vision|sight)|vision\s+(?:lost|gone)|sudden\w*\s+(?:can'?t|cannot)\s+see",
            r"sudden\w*\s+confus",
        ),
        "en",
    ),
    PhraseRule(
        "redflag_self_harm",
        (
            r"suicid",
            r"self[\s-]?harm",
            r"kill\s+myself",
            r"end\s+my\s+life",
            r"ending\s+it\s+all",
            r"(?:don'?t|do\s+not)\s+want\s+to\s+live",
            r"no\s+reason\s+to\s+live",
            r"want\s+to\s+die",
            r"(?:cutting|hurting|harming)\s+myself",
            r"overdose",
            r"too\s+many\s+(?:\w+\s+)?(?:pills|tablets)",
            r"mar\s+jaana|marna\s+chaht|jeena\s+nahi",
        ),
        "en+hi-Latn",
    ),
    PhraseRule(
        "redflag_poisoning",
        (
            r"swallow\w*\s+(?:\w+\s+){0,2}(?:poison|bleach|acid|kerosene|pesticide|phenyl|chemical|tablets|pills|battery)",
            r"(?<!food )poison",
            r"overdose",
            r"zeh[ae]r",
        ),
        "en+hi-Latn",
    ),
    PhraseRule(
        "redflag_bleeding",
        (
            _near(
                r"blood|bleed|khoon",
                r"vomit|throw\w*\s+up|cough|won'?t\s+stop|wont\s+stop|not\s+stop|heav|a\s+lot"
                r"|ulti|beh|band\s+nahi",
                5,
            ),
            r"(?:black|tarry)\s+(?:tarry\s+)?stool",
            r"bleeding\s+heavily|heavily\s+bleeding",
            _near(r"pregnan", r"bleed", 4),
        ),
        "en+hi-Latn",
    ),
)

SPECIALTY_RULES: tuple[PhraseRule, ...] = (
    PhraseRule("specialty_orthopaedics", ("knee", "back pain", "fracture", "joint", "shoulder"), "en"),
    PhraseRule("specialty_cardiology", ("palpitation", "heart", "high bp", "blood pressure"), "en"),
    PhraseRule("specialty_dermatology", ("rash", "skin", "itching", "acne", "pimple"), "en"),
    PhraseRule(
        "specialty_ent", ("ear pain", "sore throat", "sinus", "hearing", "ringing in", "tinnitus"), "en"
    ),
    PhraseRule("specialty_pulmonology", ("cough", "wheezing", "asthma"), "en"),
    PhraseRule("specialty_gastroenterology", ("stomach", "vomiting", "loose motion", "acidity"), "en"),
    PhraseRule("specialty_neurology", ("migraine", "seizure", "numbness", "headache"), "en"),
    PhraseRule(
        "specialty_general_medicine",
        ("fever", "body ache", "fatigue", "tired", "check-up", "checkup", "bukhar", "khansi"),
        "en+hi-Latn",
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


# Negation is deliberately conservative: a missed emergency costs far more than a false alarm.
# A phrase is ignored only when an unambiguous negation sits directly before it, in the same clause
# ("no chest pain", "not having chest pain", "denies chest pain"), or, for romanised Hindi, when the
# phrase is immediately followed by "nahi hai" ("seene mein dard nahi hai"). Anything less certain fires.
_NEGATION_CUES = frozenset(
    {
        "no",
        "not",
        "without",
        "denies",
        "deny",
        "never",
        "dont",
        "don't",
        "doesnt",
        "doesn't",
        "didnt",
        "didn't",
    }
)
_NEGATION_FILLERS = frozenset(
    {"any", "have", "having", "had", "has", "feel", "feeling", "experiencing", "got"}
)
_CLAUSE_BREAK = re.compile(r"[,.;:!?]|\b(?:but|and|though|although|lekin|par|aur)\b")
_WORD = re.compile(r"[a-z']+")
_HINDI_NEGATED_AFTER = re.compile(r"^\s+(?:nahi|nahin|nhi)\s+(?:hai|he|h)\b")


def _is_negated(lowered: str, start: int, end: int) -> bool:
    clause = _CLAUSE_BREAK.split(lowered[:start])[-1]
    words = _WORD.findall(clause)
    while words and words[-1] in _NEGATION_FILLERS:
        words.pop()
    # A negated list: "without chest pain or breathlessness" negates both items.
    if words and words[-1] == "or":
        words = words[:-1][:-3] if len(words) > 4 else words[:1]
        while words and words[-1] in _NEGATION_FILLERS:
            words.pop()
    if words and words[-1] in _NEGATION_CUES:
        return True
    return bool(_HINDI_NEGATED_AFTER.match(lowered[end:]))


def _fires(lowered: str, phrase: str) -> bool:
    """True if any occurrence of `phrase` is not clearly negated.

    Matches are tried at EVERY start position (a zero-width lookahead), not just non-overlapping
    ones: a greedy concept pattern can span "chest pain but chest tightness" from the first, negated
    "chest" and hide the second, un-negated one. Leading boundary only, so "breathless" still
    matches "breathlessness".
    """
    return any(
        not _is_negated(lowered, m.start(), m.start() + len(m.group(1)))
        for m in re.finditer(rf"(?<![a-z])(?=({phrase}))", lowered)
    )


def match_red_flags(text: str) -> list[str]:
    lowered = text.lower()
    return sorted(
        rule.rule_id for rule in RED_FLAG_RULES if any(_fires(lowered, phrase) for phrase in rule.phrases)
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


# ---- structured safety screen --------------------------------------------------------------------
# Free-text matching cannot be a complete emergency gate: on held-out phrasings the patterns above
# catch only a minority of emergencies. So every routine triage also asks these questions as explicit
# yes/no taps. Recall then no longer depends on how the patient phrased anything. Any "yes" is an
# emergency. Wording is an engineering draft pending clinical sign-off, like the rules above.
@dataclass(frozen=True)
class SafetyQuestion:
    key: str
    question: str
    rule_id: str


SAFETY_SCREEN: tuple[SafetyQuestion, ...] = (
    SafetyQuestion("chest_pain", "Chest pain, pressure or tightness right now?", "redflag_chest_pain"),
    SafetyQuestion(
        "breathing", "Trouble breathing, choking, or lips or face turning blue?", "redflag_breathing"
    ),
    SafetyQuestion(
        "unconscious", "Fainted, had a fit, or someone won't wake up or respond?", "redflag_unconscious"
    ),
    SafetyQuestion(
        "stroke",
        "Sudden weakness or numbness on one side, a drooping face, or slurred speech?",
        "redflag_stroke",
    ),
    SafetyQuestion(
        "bleeding", "Heavy bleeding that won't stop, or vomiting or coughing up blood?", "redflag_bleeding"
    ),
    SafetyQuestion(
        "poisoning", "Swallowed poison, chemicals or too many tablets (overdose)?", "redflag_poisoning"
    ),
    SafetyQuestion("self_harm", "Thoughts of harming yourself or ending your life?", "redflag_self_harm"),
)


def screen_red_flags(answers: object) -> list[str] | None:
    """Rule ids for every 'yes'. None if the answers are incomplete or malformed (ask again)."""
    if not isinstance(answers, dict):
        return None
    if set(answers) != {q.key for q in SAFETY_SCREEN} or not all(
        isinstance(v, bool) for v in answers.values()
    ):
        return None
    return sorted(q.rule_id for q in SAFETY_SCREEN if answers[q.key])
