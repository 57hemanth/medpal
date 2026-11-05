import pytest

from services.agent.triage.rules import (
    RED_FLAG_RULES,
    RULESET_STATUS,
    RULESET_VERSION,
    match_red_flags,
    match_specialty,
)


def test_red_flag_rules_are_versioned_drafts():
    assert RULESET_VERSION.startswith("triage-draft-")
    assert RULESET_STATUS == "draft"
    assert all(rule.status == "draft" and rule.provenance for rule in RED_FLAG_RULES)


def test_red_flags_return_stable_rule_ids_without_duplicates():
    assert match_red_flags("Chest pain and seene mein dard") == ["redflag_chest_pain"]
    assert match_red_flags("He fainted and can't breathe") == [
        "redflag_breathing",
        "redflag_unconscious",
    ]


def test_specialty_rules_route_common_complaints():
    assert match_specialty("knee pain for a week").specialty == "Orthopaedics"
    assert match_specialty("skin rash and itching").specialty == "Dermatology"
    assert match_specialty("fever and body ache").specialty == "General Medicine"


def test_uncertain_specialty_is_marked_for_clarification():
    match = match_specialty("I feel strange")

    assert match.specialty == "General Medicine"
    assert match.confidence < 0.72
    assert match.needs_clarification


# ---- negation: conservative by design. Missing a real emergency is far worse than a false alarm,
# so a phrase is ignored only when the negation is unambiguous and in the same clause.


@pytest.mark.parametrize(
    "text",
    [
        "no chest pain, just a mild skin rash on my arm",
        "not having chest pain, only a cough",
        "without chest pain or breathlessness, mild fever",
        "patient denies chest pain",
        "I don't have chest pain, it's my knee",
        "seene mein dard nahi hai, bas khansi hai",
    ],
)
def test_clearly_negated_red_flags_do_not_fire(text):
    assert match_red_flags(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "no relief from chest pain since morning",  # "no" negates relief, not the pain
        "no, chest pain is getting worse",  # the comma closes the negating clause
        "no fever but chest pain since an hour",  # the negation belongs to fever
        "no chest pain but chest tightness when walking",  # another phrase is not negated
        "seene mein dard nahi ruk raha",  # "nahi" negates "ruk raha" (not stopping)
        "not sure, but I have chest pain",
        "chest pain, no fever",  # negation after the phrase in English does not negate it
    ],
)
def test_ambiguous_or_unrelated_negation_still_fires(text):
    assert "redflag_chest_pain" in match_red_flags(text)


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("sudden breathlessness since morning", "redflag_breathing"),  # suffix must still match
        ("no relief, breathlessness getting worse", "redflag_breathing"),
        ("she fainted twice today", "redflag_unconscious"),
        ("no fever or cough but chest pain", "redflag_chest_pain"),
        ("no fever or cough, chest tightness", "redflag_chest_pain"),
    ],
)
def test_recall_cases_still_fire(text, rule):
    assert rule in match_red_flags(text)
