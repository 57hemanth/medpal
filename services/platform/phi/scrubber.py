"""De-identification with Microsoft Presidio: the policy behind the single egress door.

    tokenise(text)       → ("Patient <PERSON_1> …", token_map)  identifiers replaced, reversibly
    assert_clean(text)   → second, independent pass; raises EgressBlocked if anything slipped (fail closed)
    reidentify(text, m)  → model output with tokens swapped back, inside the boundary

The token map never leaves the boundary. Aadhaar numbers are BLOCKED, never tokenised: the Aadhaar
Act restricts storing them, and a reversible map would be a store.

Entity policy follows the D4 sensitivity classes:
  direct identifiers   → tokenise (names, phones, emails, ABHA, PAN, MRN, DOB)
  quasi identifiers    → tokenise (locations, pincodes); generalisation lands with the egress adapter
  clinical content     → keep (lab values, drugs, symptoms are what the model needs)
  DATE_TIME (generic)  → keep: report dates carry clinical meaning; a labelled DOB is caught as DOB
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

from presidio_analyzer import AnalyzerEngine, EntityRecognizer, RecognizerResult
from presidio_analyzer.predefined_recognizers import (
    InAadhaarRecognizer,
    InPanRecognizer,
    InPassportRecognizer,
    InVehicleRegistrationRecognizer,
    InVoterRecognizer,
)

from .recognizers import india_recognizers, known_identity_recognizer

Action = Literal["tokenise", "block", "keep"]

POLICY: dict[str, Action] = {
    "PERSON": "tokenise",
    "PHONE_NUMBER": "tokenise",
    "IN_PHONE": "tokenise",
    "EMAIL_ADDRESS": "tokenise",
    "ABHA_NUMBER": "tokenise",
    "ABHA_ADDRESS": "tokenise",
    "IN_PAN": "tokenise",
    "IN_VOTER": "tokenise",
    "IN_PASSPORT": "tokenise",
    "IN_VEHICLE_REGISTRATION": "tokenise",
    "MEDICAL_LICENSE": "tokenise",
    "UUID": "tokenise",  # internal ids round-trip via the token map, so patient_ids never leave
    "MRN": "tokenise",
    "DOB": "tokenise",
    "LOCATION": "tokenise",
    "IN_PINCODE": "tokenise",
    "IP_ADDRESS": "tokenise",
    "CREDIT_CARD": "tokenise",
    "IBAN_CODE": "tokenise",
    "URL": "tokenise",
    "IN_AADHAAR": "block",
    "DATE_TIME": "keep",
    "NRP": "keep",  # nationality/religious/political group: flagged for review in D4, not removed here
}

# Entities whose survival past tokenisation must block egress (second pass).
DIRECT_IDENTIFIERS = frozenset(
    {
        "PERSON",
        "PHONE_NUMBER",
        "IN_PHONE",
        "EMAIL_ADDRESS",
        "ABHA_NUMBER",
        "ABHA_ADDRESS",
        "IN_PAN",
        "IN_VOTER",
        "IN_PASSPORT",
        "MRN",
        "DOB",
        "IN_AADHAAR",
    }
)

TOKEN_RE = re.compile(r"<([A-Z_]+)_(\d+)>")
DEFAULT_THRESHOLD = 0.5


class BlockedIdentifier(ValueError):
    """Input contains an identifier we must not store or forward (e.g. Aadhaar)."""

    def __init__(self, entity_types: list[str]) -> None:
        super().__init__(f"blocked identifier(s): {', '.join(sorted(set(entity_types)))}")
        self.entity_types = entity_types


class EgressBlocked(RuntimeError):
    """Second-pass detector found a direct identifier in text about to leave the boundary."""

    def __init__(self, findings: list[tuple[str, float]]) -> None:
        super().__init__(
            f"egress blocked: {len(findings)} identifier(s) remain: {sorted({f[0] for f in findings})}"
        )
        self.findings = findings


@dataclass
class TokenMap:
    """value ↔ token, per conversation/run. Same value → same token, so the model sees consistent text."""

    by_token: dict[str, str] = field(default_factory=dict)
    by_value: dict[tuple[str, str], str] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)

    def token_for(self, entity: str, value: str) -> str:
        key = (entity, value.strip().lower())
        if key not in self.by_value:
            self.counters[entity] = self.counters.get(entity, 0) + 1
            token = f"<{entity}_{self.counters[entity]}>"
            self.by_value[key] = token
            self.by_token[token] = value
        return self.by_value[key]


@dataclass(frozen=True)
class ScrubResult:
    text: str
    token_map: TokenMap
    entities: list[str]  # entity types replaced, for the audit event (never the values)


_FOREIGN_RECOGNIZERS = (
    "NhsRecognizer",
    "UsBankRecognizer",
    "UsItinRecognizer",
    "UsLicenseRecognizer",
    "UsPassportRecognizer",
    "UsSsnRecognizer",
)


@lru_cache(maxsize=2)
def _engine(*, hinglish: bool = False) -> AnalyzerEngine:
    """English engine: spaCy en_core_web_lg NER + pattern recognisers + India recognisers.
    Hinglish engine: the same, minus spaCy's NER recogniser, which mislabels romanised Hindi as
    PERSON. It must be removed up front: Presidio de-duplicates overlapping results internally, so
    filtering spaCy spans afterwards would also lose the name-list hits nested inside them."""
    engine = AnalyzerEngine()  # spaCy en_core_web_lg, pinned in pyproject
    # Other countries' recognisers misfire on Indian numbers (UK NHS claimed 10-digit mobiles).
    for foreign in _FOREIGN_RECOGNIZERS:
        engine.registry.remove_recognizer(foreign)
    # Presidio's own India recognisers are not loaded by default for "en": add them explicitly.
    for builtin in (
        InAadhaarRecognizer,
        InPanRecognizer,
        InVoterRecognizer,
        InPassportRecognizer,
        InVehicleRegistrationRecognizer,
    ):
        engine.registry.add_recognizer(builtin())
    for recognizer in india_recognizers():
        engine.registry.add_recognizer(recognizer)
    if hinglish:
        engine.registry.remove_recognizer("SpacyRecognizer")
    return engine


def _resolve_overlaps(results: list[RecognizerResult]) -> list[RecognizerResult]:
    """Keep non-overlapping spans, ranked by SEVERITY first (block > tokenise > keep), then score,
    then length. Severity must come first: spaCy labels digit runs as DATE_TIME (0.85, a "keep"
    type), which would otherwise shadow a phone or ABHA number (0.55-0.7) and let it leak."""
    severity = {"block": 2, "tokenise": 1, "keep": 0}

    def rank(r: RecognizerResult) -> tuple[int, float, int]:
        return (severity[POLICY.get(r.entity_type, "tokenise")], r.score, r.end - r.start)

    kept: list[RecognizerResult] = []
    for r in sorted(results, key=rank, reverse=True):
        if all(r.end <= k.start or r.start >= k.end for k in kept):
            kept.append(r)
    return sorted(kept, key=lambda r: r.start)


def _merge_adjacent(text: str, results: list[RecognizerResult]) -> list[RecognizerResult]:
    """Join same-type spans separated only by spaces ("neha" + "kulkarni" → one PERSON)."""
    merged: list[RecognizerResult] = []
    for r in results:
        prev = merged[-1] if merged else None
        if prev and prev.entity_type == r.entity_type and text[prev.end : r.start].strip() == "":
            merged[-1] = RecognizerResult(r.entity_type, prev.start, r.end, max(prev.score, r.score))
        else:
            merged.append(r)
    return merged


def _load_words(filename: str) -> frozenset[str]:
    path = Path(__file__).parent / "data" / filename
    lines = (ln.strip() for ln in path.read_text(encoding="utf-8").splitlines())
    return frozenset(w for ln in lines if ln and not ln.startswith("#") for w in ln.split())


# See data/hinglish_words.txt for why this list exists and what it deliberately excludes.
_HINGLISH_WORDS = _load_words("hinglish_words.txt")
_WORD_RE = re.compile(r"[a-z]+")
_NAME_CUE = re.compile(r"\b(?:naam|name is|named|called)\s+(?P<name>[a-z]+(?:\s+[a-z]+)?)", re.IGNORECASE)


def looks_hinglish(text: str) -> bool:
    words = _WORD_RE.findall(text.lower())
    hits = sum(w in _HINGLISH_WORDS for w in words)
    return hits >= 2 and hits / max(len(words), 1) >= 0.2


_MAX_NAME_WORDS = 4


def _implausible_ner_name(text: str, result: RecognizerResult) -> bool:
    """A 'person' the English NER found that runs longer than a name ever does is a misread sentence.

    spaCy reads short romanised-Hindi sentences as one long name: "apni jaan lena chahta hoon" ("I want
    to end my life") became <PERSON_1>, erasing the one thing the safety check must see. Known names,
    the names list and 'naam X' cues are separate recognisers and are not affected by this rule.
    """
    if result.entity_type != "PERSON":
        return False
    source = (result.recognition_metadata or {}).get("recognizer_name", "")
    if "spacy" not in str(source).lower():
        return False
    return len(text[result.start : result.end].split()) > _MAX_NAME_WORDS


def _name_cue_results(text: str) -> list[RecognizerResult]:
    """'naam shobha tai' / 'name is ravi': cover names the lists don't know, in Hinglish mode."""
    return [RecognizerResult("PERSON", m.start("name"), m.end("name"), 0.7) for m in _NAME_CUE.finditer(text)]


def analyze(
    text: str, *, known_names: list[str] | None = None, threshold: float = DEFAULT_THRESHOLD
) -> list[RecognizerResult]:
    """Detect identifiers. `known_names` = identities we already know for this request (the caller,
    their consented patients, doctors): matched case-insensitively, the strongest defence for
    lowercase and Hinglish text.

    Hinglish mode: spaCy NER is switched off (it mislabels Hindi words as PERSON); names come from
    known identities, the common-names list and 'naam X' cues instead."""
    known = known_identity_recognizer(known_names or [])
    ad_hoc: list[EntityRecognizer] = [known] if known is not None else []
    hinglish = looks_hinglish(text)
    results = _engine(hinglish=hinglish).analyze(
        text=text, language="en", score_threshold=threshold, ad_hoc_recognizers=ad_hoc
    )
    if hinglish:
        results += _name_cue_results(text)
    results = [r for r in results if not _implausible_ner_name(text, r)]
    # Our own tokens must never be re-detected as entities.
    token_spans = [(m.start(), m.end()) for m in TOKEN_RE.finditer(text)]
    results = [r for r in results if not any(s <= r.start and r.end <= e for s, e in token_spans)]
    return _merge_adjacent(text, _resolve_overlaps(results))


def tokenise(
    text: str,
    token_map: TokenMap | None = None,
    *,
    known_names: list[str] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> ScrubResult:
    """Replace identifiers with stable tokens. Raises BlockedIdentifier for blocked entity types."""
    token_map = token_map or TokenMap()
    results = analyze(text, known_names=known_names, threshold=threshold)
    blocked = [r.entity_type for r in results if POLICY.get(r.entity_type) == "block"]
    if blocked:
        raise BlockedIdentifier(blocked)

    out, cursor, replaced = [], 0, []
    for r in results:
        if POLICY.get(r.entity_type, "tokenise") != "tokenise":  # unknown types fail safe: tokenise
            continue
        out.append(text[cursor : r.start])
        out.append(token_map.token_for(r.entity_type, text[r.start : r.end]))
        replaced.append(r.entity_type)
        cursor = r.end
    out.append(text[cursor:])
    return ScrubResult(text="".join(out), token_map=token_map, entities=replaced)


def assert_clean(
    text: str, *, known_names: list[str] | None = None, threshold: float = DEFAULT_THRESHOLD
) -> None:
    """Fail closed: raise if any direct identifier is still detectable in outbound text."""
    findings = [
        (r.entity_type, r.score)
        for r in analyze(text, known_names=known_names, threshold=threshold)
        if r.entity_type in DIRECT_IDENTIFIERS
    ]
    if findings:
        raise EgressBlocked(findings)


def reidentify(text: str, token_map: TokenMap) -> str:
    """Swap tokens back to original values. Unknown tokens are left as-is (and are visible to review)."""
    return TOKEN_RE.sub(lambda m: token_map.by_token.get(m.group(0), m.group(0)), text)
