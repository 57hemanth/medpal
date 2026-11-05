"""The judge is only trusted after calibration against clinician-reviewed labels."""

import json

from evals.judge import MIN_REVIEWED, SET, calibrate, cohen_kappa


def cases(n: int, reviewed: bool) -> list[dict[str, object]]:
    return [{"faithful": i % 2 == 0, "reviewed": reviewed} for i in range(n)]


def test_draft_labels_never_calibrate_a_judge():
    shipped = [json.loads(line) for line in SET.read_text().splitlines()]
    assert len(shipped) >= 20 and not any(c["reviewed"] for c in shipped)  # drafts until a clinician reviews
    result = calibrate(shipped, [bool(c["faithful"]) for c in shipped])  # even a "perfect" judge
    assert not result.calibrated and "clinician-reviewed" in result.why


def test_a_judge_that_agrees_with_reviewed_labels_is_calibrated():
    c = cases(MIN_REVIEWED, reviewed=True)
    result = calibrate(c, [bool(x["faithful"]) for x in c])
    assert result.calibrated and result.kappa == 1.0


def test_a_judge_that_always_says_faithful_is_not_calibrated():
    c = cases(MIN_REVIEWED, reviewed=True)
    result = calibrate(c, [True] * MIN_REVIEWED)  # 50% agreement, but no skill: kappa 0
    assert not result.calibrated and result.kappa == 0.0


def test_kappa_matches_a_hand_computed_value():
    human = [True, True, False, False, True, False, True, False]
    judge = [True, False, False, False, True, True, True, False]
    assert cohen_kappa(human, judge) == 0.5
