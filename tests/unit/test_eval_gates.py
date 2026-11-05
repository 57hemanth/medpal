"""Release gates over the evaluation sets (see evals/run.py). A failing gate fails the build."""

from evals.run import GATES, run


def test_red_flag_recall_is_total_on_the_eval_set():
    report = run()
    missed = [f for f in report.failures if f["kind"] == "missed_red_flag"]
    assert report.red_flag_recall == GATES["red_flag_recall"], missed


def test_over_triage_stays_under_the_cap():
    assert run().over_triage <= GATES["over_triage_max"]


def test_specialty_accuracy_meets_the_bar():
    assert run().specialty_accuracy >= GATES["specialty_accuracy"]


def test_held_out_set_is_reported_but_not_tuned_against():
    report = run()
    assert report.holdout_cases >= 30  # it exists and is scored on every run
    # Deliberately no recall threshold: the held-out figure measures how well free-text rules
    # generalise. The structured safety screen, not the rules, is what makes triage safe.


def test_advice_questions_about_records_always_go_to_a_doctor():
    report = run()
    missed = [f for f in report.failures if f["kind"] == "advice_answered"]
    assert report.doctor_review_recall == GATES["doctor_review_recall"], missed


def test_plain_report_questions_are_not_refused():
    assert run().over_refusal <= GATES["over_refusal_max"]
