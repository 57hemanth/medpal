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
