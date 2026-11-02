"""India-specific Presidio recognisers. Presidio's built-ins cover names, emails and generic phones,
but not ABHA, Aadhaar, PAN or Indian mobile formats (D4 data contracts).

Each recogniser lists its context words: Presidio boosts the score when one appears nearby.
"""

import re
from pathlib import Path

from presidio_analyzer import Pattern, PatternRecognizer

# --- Verhoeff checksum (used by Aadhaar) -------------------------------------------------------
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_valid(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def verhoeff_check_digit(number: str) -> str:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


class AadhaarRecognizer(PatternRecognizer):
    """12 digits, first digit 2-9, optional 4-4-4 spacing, valid Verhoeff checksum.
    Policy: BLOCK. The Aadhaar Act restricts storing the number, so we neither store nor tokenise it."""

    def __init__(self) -> None:
        super().__init__(
            supported_entity="IN_AADHAAR",
            patterns=[Pattern("aadhaar", r"(?<!\d)[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?!\d)", 0.5)],
            context=["aadhaar", "aadhar", "uid", "uidai"],
        )

    def validate_result(self, pattern_text: str) -> bool | None:
        digits = re.sub(r"\D", "", pattern_text)
        return len(digits) == 12 and verhoeff_valid(digits)


_NAMES_FILE = Path(__file__).parent / "data" / "indian_names.txt"


def common_indian_names() -> list[str]:
    words: set[str] = set()
    for line in _NAMES_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "[")):
            words.update(w for w in line.split() if len(w) >= 3)
    return sorted(words)


def name_list_recognizer() -> PatternRecognizer:
    """Safety net for lowercase/Hinglish text where spaCy NER misses names (pre-mortem F9)."""
    return PatternRecognizer(
        supported_entity="PERSON",
        name="IndianNameListRecognizer",
        deny_list=common_indian_names(),
        deny_list_score=0.6,
        global_regex_flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )


def known_identity_recognizer(names: list[str]) -> PatternRecognizer | None:
    """Ad-hoc recogniser for identities we already know in this request (caller, consented patients,
    doctors). Matches the full name and each part of 3+ characters, case-insensitively."""
    terms = {t for n in names for t in [n, *n.split()] if len(t.strip()) >= 3}
    if not terms:
        return None
    return PatternRecognizer(
        supported_entity="PERSON",
        name="KnownIdentityRecognizer",
        deny_list=sorted(terms, key=len, reverse=True),
        deny_list_score=0.95,
        global_regex_flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )


def india_recognizers() -> list[PatternRecognizer]:
    return [
        name_list_recognizer(),
        PatternRecognizer(
            supported_entity="IN_PHONE",
            patterns=[
                # +91 / 0 prefix optional; 10 digits starting 6-9; common 5-5 or 3-3-4 spacing
                Pattern("in_mobile", r"(?<![\d+])(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)", 0.7),
                Pattern(
                    "in_mobile_334", r"(?<![\d+])(?:\+91[\s-]?)?[6-9]\d{2}[\s-]\d{3}[\s-]\d{4}(?!\d)", 0.7
                ),
            ],
            context=["phone", "mobile", "mob", "contact", "call", "whatsapp", "ph"],
        ),
        PatternRecognizer(
            supported_entity="ABHA_NUMBER",
            patterns=[
                Pattern("abha_hyphenated", r"(?<!\d)\d{2}-\d{4}-\d{4}-\d{4}(?!\d)", 0.9),
                Pattern("abha_plain", r"(?<!\d)\d{14}(?!\d)", 0.3),  # needs context to pass threshold
            ],
            context=["abha", "health id", "healthid", "abdm", "ndhm"],
        ),
        PatternRecognizer(
            supported_entity="ABHA_ADDRESS",
            patterns=[Pattern("abha_address", r"\b[A-Za-z0-9._]{3,32}@(?:abdm|sbx)\b", 0.9)],
        ),
        PatternRecognizer(
            supported_entity="IN_PAN",
            patterns=[Pattern("pan", r"\b[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]\b", 0.8)],
            context=["pan", "income tax", "permanent account"],
        ),
        PatternRecognizer(
            supported_entity="IN_PINCODE",
            patterns=[
                Pattern("pincode", r"(?<!\d)[1-9]\d{2}\s?\d{3}(?!\d)", 0.2)
            ],  # passes only with context
            context=["pincode", "pin code", "pin", "postal"],
        ),
        PatternRecognizer(
            supported_entity="MRN",
            # Client MRN format is an open discovery question; this catches labelled ids meanwhile.
            patterns=[
                Pattern("mrn_labelled", r"\b(?:MRN|UHID|IP\s?No|OP\s?No)[:#.\s-]*[A-Z0-9-]{4,}\b", 0.85)
            ],
        ),
        PatternRecognizer(
            supported_entity="DOB",
            patterns=[
                Pattern(
                    "dob_labelled",
                    r"\b(?:DOB|D\.O\.B\.?|date of birth|born on)[:\s]*"
                    r"(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
                    0.9,
                )
            ],
        ),
        AadhaarRecognizer(),
    ]
