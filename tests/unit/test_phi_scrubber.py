"""Presidio de-identification policy: identifier classes, Aadhaar blocking, names in English and Hinglish.

Tests both directions: identifiers must not leak, AND clinical content must not be over-scrubbed
(romanised Hindi once lost "fever for ten days" to a spaCy PERSON false positive).
All names and numbers here are synthetic.
"""

import pytest

from services.platform.phi import scrubber
from services.platform.phi.recognizers import verhoeff_check_digit, verhoeff_valid
from services.platform.phi.scrubber import BlockedIdentifier, EgressBlocked, TokenMap


def scrub(text: str, **kw) -> str:
    return scrubber.tokenise(text, **kw).text


# ---- direct identifiers -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phone", ["+91 98765 43210", "9876543210", "+91-9876543210", "098765 43210", "987 654 3210"]
)
def test_indian_mobile_formats_are_tokenised(phone):
    out = scrub(f"Call me on {phone} after 6 pm")
    assert phone not in out
    assert "PHONE" in out


def test_abha_number_and_address_are_tokenised():
    out = scrub("ABHA 12-3456-7890-1234, ABHA address neha.k@abdm")
    assert "12-3456-7890-1234" not in out and "neha.k@abdm" not in out
    assert "<ABHA_NUMBER_1>" in out and "<ABHA_ADDRESS_1>" in out


def test_plain_14_digit_abha_needs_context():
    assert "<ABHA_NUMBER_1>" in scrub("my abha health id is 12345678901234")
    assert "12345678901234" in scrub("invoice 12345678901234 paid")  # no context: not an ABHA


def test_pan_mrn_and_labelled_dob_are_tokenised():
    out = scrub("PAN ABCPE1234F, MRN: SAH-2024-00917, DOB 14/03/1962")
    assert "ABCPE1234F" not in out and "SAH-2024-00917" not in out and "14/03/1962" not in out


def test_report_dates_are_kept_for_clinical_meaning():
    out = scrub("Lipid panel collected on 3 Nov 2026; repeat on 17 Nov 2026.")
    assert "3 Nov 2026" in out and "17 Nov 2026" in out


def test_pincode_only_with_context():
    assert "411045" not in scrub("Address pincode 411045")
    assert "250000" in scrub("Platelets 250000 per microlitre")  # a lab value is not a pincode


# ---- Aadhaar is blocked, never stored ----------------------------------------------------------


def _synthetic_aadhaar(prefix: str = "23412341234") -> str:
    number = prefix + verhoeff_check_digit(prefix)
    assert verhoeff_valid(number)
    return number


def test_valid_aadhaar_is_blocked_not_tokenised():
    n = _synthetic_aadhaar()
    spaced = f"{n[:4]} {n[4:8]} {n[8:]}"
    for text in (f"My Aadhaar is {n}", f"aadhar {spaced}"):
        with pytest.raises(BlockedIdentifier) as exc:
            scrubber.tokenise(text)
        assert exc.value.entity_types == ["IN_AADHAAR"]


def test_twelve_digits_failing_checksum_are_not_blocked():
    n = _synthetic_aadhaar()
    wrong = n[:-1] + str((int(n[-1]) + 1) % 10)
    assert not verhoeff_valid(wrong)
    scrubber.tokenise(f"reference {wrong}")  # must not raise


# ---- names: English, lowercase, Hinglish, known identities --------------------------------------

NAMES = [
    "Neha Kulkarni",
    "Venkatesh Rao",
    "Lakshmi Narayanan",
    "Mohammed Imran",
    "Kavita Deshpande",
    "Suresh Kumar",
    "Anjali Gupta",
    "Ramesh Iyer",
    "Sunita Patil",
    "Arjun Reddy",
]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize(
    "template",
    [
        "Patient {n} presented with fever.",
        "Referred by Dr. {n} for an ECG.",
        "my mother {lower} has knee pain since 2 weeks",
        "meri maa {lower} ko seene mein dard hai",
    ],
)
def test_names_do_not_leak(name, template):
    out = scrub(template.format(n=name, lower=name.lower()))
    assert not any(part.lower() in out.lower() for part in name.split()), out


def test_known_identity_catches_names_no_list_knows():
    text = "meri dadi shobha tai ko das din se bukhar hai"
    assert scrub(text, known_names=["Shobha Tai Kale"]) == "meri dadi <PERSON_1> ko das din se bukhar hai"


def test_name_cue_in_hinglish_keeps_the_cue_word():
    assert scrub("papa ka naam ganpat rao hai") == "papa ka naam <PERSON_1> hai"


# ---- clinical content must survive (over-scrub guard) -------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "HbA1c 6.8 %, LDL 162 mg/dL, fasting glucose 126 mg/dL.",
        "Start atorvastatin 10 mg nightly; review in two weeks.",
        "Metformin 500 mg BD, Telmisartan 40 mg OD.",
        "Dull ache in left arm, breathless since morning, diabetic.",
        "mujhe teen din se khansi aur bukhar hai",
        "meri dadi ko das din se bukhar hai",
        "unko saans lene mein takleef hai aur chakkar aa rahe hain",
    ],
)
def test_clinical_text_is_unchanged(text):
    assert scrub(text) == text


# ---- reversibility and fail-closed egress -------------------------------------------------------


def test_round_trip_and_stable_tokens():
    text = "Neha Kulkarni called. Please ask Neha Kulkarni about her HbA1c."
    result = scrubber.tokenise(text)
    assert result.text.count("<PERSON_1>") == 2
    assert scrubber.reidentify(result.text, result.token_map) == text


def test_token_map_is_shared_across_turns():
    tm = TokenMap()
    a = scrubber.tokenise("Neha Kulkarni has fever", tm).text
    b = scrubber.tokenise("Is Neha Kulkarni diabetic?", tm).text
    assert "<PERSON_1>" in a and "<PERSON_1>" in b


def test_already_tokenised_text_is_stable():
    once = scrub("Patient Neha Kulkarni, mobile 9876543210")
    assert scrub(once) == once


def test_assert_clean_blocks_a_leftover_identifier():
    with pytest.raises(EgressBlocked):
        scrubber.assert_clean("Draft for Neha Kulkarni, call 9876543210")
    scrubber.assert_clean(scrub("Draft for Neha Kulkarni, call 9876543210"))  # tokenised: passes


def test_entities_report_types_never_values():
    result = scrubber.tokenise("Neha Kulkarni, 9876543210")
    assert set(result.entities) == {"PERSON", "IN_PHONE"}
    assert all("Neha" not in e for e in result.entities)


@pytest.mark.parametrize(
    "text",
    [
        "apni jaan lena chahta hoon",  # "I want to take my own life": was erased as one long <PERSON>
        "main khud ko khatam karna chahta hoon",
        "mujhe jeene ka mann nahi karta",
    ],
)
def test_short_hinglish_safety_statements_survive_scrubbing(text):
    assert scrubber.tokenise(text).text == text


def test_names_are_still_removed_next_to_hinglish_safety_words():
    out = scrubber.tokenise("mera naam asha verma hai aur apni jaan lena chahti hoon").text
    assert "asha" not in out.lower() and "jaan lena" in out
