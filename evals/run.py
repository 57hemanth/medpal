"""Run the evaluation sets and report measured numbers, not adjectives.

    uv run python -m evals.run            # print the report and write evals/runs/<timestamp>.json
    uv run python -m evals.run --check    # also exit non-zero if a release gate fails

Sets:
  * triage_red_flags.jsonl, triage_specialty.jsonl: tuned against; the gates below apply to them.
  * triage_red_flags_holdout2.jsonl: HELD OUT. Never tune rules against it. Its recall is reported as a
    generalisation figure: free-text rules alone miss most unseen phrasings, which is why every routine
    triage also runs the structured safety screen (any "yes" is an emergency, whatever the wording).

Gates (the build fails if any is missed):
  * red-flag recall = 100%: every emergency phrasing in the set must raise a red flag;
  * over-triage <= 10%: share of non-emergencies wrongly escalated (a flooded emergency desk stops
    being trusted, so this is reported and capped, not ignored);
  * specialty accuracy >= 85% on the specialty set;
  * records doctor-review recall = 100% and over-refusal <= 10% on records_doctor_review.jsonl: questions
    asking for medical advice must go to a doctor; plain report questions must stay answerable.
    records_doctor_review_holdout.jsonl is held out and reported only; the model's needs_doctor flag is
    the second net for phrasings the rules miss, measured live by `make live-check`.
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from services.agent.triage.rules import RULESET_STATUS, RULESET_VERSION, match_red_flags, match_specialty
from services.records.qa import needs_doctor_review

SETS = Path(__file__).parent / "sets"
RUNS = Path(__file__).parent / "runs"

GATES = {
    "red_flag_recall": 1.0,
    "over_triage_max": 0.10,
    "specialty_accuracy": 0.85,
    "doctor_review_recall": 1.0,
    "over_refusal_max": 0.10,
}


@dataclass
class Report:
    ruleset_version: str = RULESET_VERSION
    ruleset_status: str = RULESET_STATUS
    red_flag_positives: int = 0
    red_flag_negatives: int = 0
    red_flag_recall: float = 0.0
    red_flag_rule_accuracy: float = 0.0
    over_triage: float = 0.0
    holdout_cases: int = 0
    holdout_recall_rules_only: float = 0.0
    holdout_over_triage: float = 0.0
    specialty_cases: int = 0
    specialty_accuracy: float = 0.0
    doctor_review_cases: int = 0
    doctor_review_recall: float = 0.0
    over_refusal: float = 0.0
    doctor_review_holdout_recall: float = 0.0
    doctor_review_holdout_over_refusal: float = 0.0
    specialty_holdout_right: float = 0.0
    specialty_holdout_wrong: float = 0.0
    specialty_holdout_unsure: float = 0.0
    failures: list[dict[str, object]] = field(default_factory=list)
    gates: dict[str, bool] = field(default_factory=dict)


def _load(name: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in (SETS / name).read_text().splitlines() if line.strip()]


def run() -> Report:
    report = Report()
    red_flag_cases = _load("triage_red_flags.jsonl")
    positives = [c for c in red_flag_cases if c["expect_red_flag"]]
    negatives = [c for c in red_flag_cases if not c["expect_red_flag"]]
    report.red_flag_positives, report.red_flag_negatives = len(positives), len(negatives)

    caught = rule_right = 0
    for case in positives:
        flags = match_red_flags(str(case["text"]))
        if flags:
            caught += 1
            rule_right += case.get("expect_rule") in flags
        else:
            report.failures.append({"id": case["id"], "kind": "missed_red_flag", "text": case["text"]})
    false_alarms = 0
    for case in negatives:
        flags = match_red_flags(str(case["text"]))
        if flags:
            false_alarms += 1
            report.failures.append(
                {"id": case["id"], "kind": "over_triage", "text": case["text"], "got": flags}
            )
    report.red_flag_recall = round(caught / len(positives), 4) if positives else 0.0
    report.red_flag_rule_accuracy = round(rule_right / len(positives), 4) if positives else 0.0
    report.over_triage = round(false_alarms / len(negatives), 4) if negatives else 0.0

    holdout = _load("triage_red_flags_holdout2.jsonl")
    h_pos = [c for c in holdout if c["expect_red_flag"]]
    h_neg = [c for c in holdout if not c["expect_red_flag"]]
    report.holdout_cases = len(holdout)
    report.holdout_recall_rules_only = round(
        sum(bool(match_red_flags(str(c["text"]))) for c in h_pos) / len(h_pos), 4
    )
    report.holdout_over_triage = round(
        sum(bool(match_red_flags(str(c["text"]))) for c in h_neg) / len(h_neg), 4
    )

    specialty_cases = _load("triage_specialty.jsonl")
    right = 0
    for case in specialty_cases:
        got = match_specialty(str(case["text"]))
        if got.specialty == case["expect_specialty"] and not got.needs_clarification:
            right += 1
        else:
            report.failures.append(
                {
                    "id": case["id"],
                    "kind": "wrong_specialty",
                    "text": case["text"],
                    "expected": case["expect_specialty"],
                    "got": got.specialty,
                }
            )
    report.specialty_cases = len(specialty_cases)
    report.specialty_accuracy = round(right / len(specialty_cases), 4) if specialty_cases else 0.0

    def score(cases: list[dict[str, object]]) -> tuple[float, float, list[dict[str, object]]]:
        pos = [c for c in cases if c["expect_doctor"]]
        neg = [c for c in cases if not c["expect_doctor"]]
        missed = [c for c in pos if not needs_doctor_review(str(c["question"]))]
        refused = [c for c in neg if needs_doctor_review(str(c["question"]))]
        recall = round(1 - len(missed) / len(pos), 4) if pos else 1.0
        over = round(len(refused) / len(neg), 4) if neg else 0.0
        wrong = [{"id": c["id"], "kind": "advice_answered", "text": c["question"]} for c in missed] + [
            {"id": c["id"], "kind": "fact_refused", "text": c["question"]} for c in refused
        ]
        return recall, over, wrong

    # Specialty on phrasings the rules were never tuned on: reported, not gated. With a model configured,
    # the model answers when the rules are unsure; `make live-check` measures that combination.
    unseen = _load("triage_specialty_holdout.jsonl")
    matches = [(match_specialty(str(c["text"])), c["expect"]) for c in unseen]
    n = len(unseen) or 1
    report.specialty_holdout_unsure = round(sum(m.needs_clarification for m, _ in matches) / n, 4)
    report.specialty_holdout_right = round(
        sum(not m.needs_clarification and m.specialty in e for m, e in matches) / n,
        4,  # type: ignore[operator]
    )
    report.specialty_holdout_wrong = round(
        sum(not m.needs_clarification and m.specialty not in e for m, e in matches) / n,
        4,  # type: ignore[operator]
    )

    review = _load("records_doctor_review.jsonl")
    report.doctor_review_cases = len(review)
    report.doctor_review_recall, report.over_refusal, wrong = score(review)
    report.failures.extend(wrong)
    held = _load("records_doctor_review_holdout.jsonl")
    report.doctor_review_holdout_recall, report.doctor_review_holdout_over_refusal, _ = score(held)

    report.gates = {
        "doctor_review_recall": report.doctor_review_recall >= GATES["doctor_review_recall"],
        "over_refusal": report.over_refusal <= GATES["over_refusal_max"],
        "red_flag_recall": report.red_flag_recall >= GATES["red_flag_recall"],
        "over_triage": report.over_triage <= GATES["over_triage_max"],
        "specialty_accuracy": report.specialty_accuracy >= GATES["specialty_accuracy"],
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="exit non-zero if a gate fails")
    args = parser.parse_args()
    report = run()
    RUNS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (RUNS / f"{stamp}.json").write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False))

    print(f"ruleset {report.ruleset_version} ({report.ruleset_status})")
    print(f"red-flag recall     {report.red_flag_recall:.0%}  ({report.red_flag_positives} emergencies)")
    print(f"right rule          {report.red_flag_rule_accuracy:.0%}")
    print(f"over-triage         {report.over_triage:.0%}  ({report.red_flag_negatives} non-emergencies)")
    print(f"specialty accuracy  {report.specialty_accuracy:.0%}  ({report.specialty_cases} cases)")
    print(
        f"held-out (rules only, not a gate): recall {report.holdout_recall_rules_only:.0%}, "
        f"over-triage {report.holdout_over_triage:.0%}  ({report.holdout_cases} cases); "
        "the structured safety screen covers what the rules miss"
    )
    print(
        "  specialty, unseen phrasings (rules only, not a gate): "
        f"right {report.specialty_holdout_right:.0%}, "
        f"wrong {report.specialty_holdout_wrong:.0%}, asks a question {report.specialty_holdout_unsure:.0%}; "
        "the model answers when the rules are unsure (make live-check)"
    )
    print(
        f"records doctor-review recall {report.doctor_review_recall:.0%}, over-refusal "
        f"{report.over_refusal:.0%}  ({report.doctor_review_cases} questions)"
    )
    print(
        f"  held-out (rules only, not a gate): recall {report.doctor_review_holdout_recall:.0%}, "
        f"over-refusal {report.doctor_review_holdout_over_refusal:.0%}; the model's needs_doctor flag "
        "is the second net (make live-check)"
    )
    for failure in report.failures:
        print(
            f"  {failure['kind']:16} {failure['id']}  {failure['text']}"
            + (f"  → {failure.get('got')}" if failure.get("got") else "")
        )
    print("gates:", ", ".join(f"{k} {'PASS' if v else 'FAIL'}" for k, v in report.gates.items()))
    if args.check and not all(report.gates.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
