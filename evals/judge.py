"""LLM-as-judge for records answers, and its calibration against human labels.

    MEDPAL_CHAT_PROVIDER=... MEDPAL_CHAT_API_KEY=... uv run python -m evals.judge

A judge is only trusted after calibration: it is run on cases a clinician has labelled, agreement is
measured with Cohen's kappa, and it is declared calibrated only if at least MIN_REVIEWED labels are
clinician-reviewed AND kappa >= MIN_KAPPA. Draft labels (reviewed: false) never count. The judge is a
signal for monitoring, never the only gate on a release: deterministic citation checks stay in front.
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from services.platform.config import get_settings
from services.platform.egress.client import EgressChatClient, ModelRequest
from services.platform.egress.providers import build_model_routes

SET = Path(__file__).parent / "sets" / "judge_calibration.jsonl"
MIN_REVIEWED = 20
MIN_KAPPA = 0.6
JUDGE_INSTRUCTIONS = (
    "You check whether an answer to a patient's question is fully supported by the report excerpt. "
    "Return faithful=true only if every claim in the answer is stated in the excerpt. Any added "
    "interpretation, diagnosis, or changed value makes it unfaithful."
)


class Verdict(BaseModel):
    faithful: bool
    reason: str


@dataclass(frozen=True)
class Calibration:
    reviewed: int
    agreement: float | None
    kappa: float | None
    calibrated: bool
    why: str


def cohen_kappa(human: list[bool], judge: list[bool]) -> float:
    n = len(human)
    observed = sum(h == j for h, j in zip(human, judge, strict=True)) / n
    p_h, p_j = sum(human) / n, sum(judge) / n
    expected = p_h * p_j + (1 - p_h) * (1 - p_j)
    return 1.0 if expected == 1 else round((observed - expected) / (1 - expected), 4)


def calibrate(cases: list[dict[str, object]], verdicts: list[bool]) -> Calibration:
    reviewed = [(bool(c["faithful"]), v) for c, v in zip(cases, verdicts, strict=True) if c.get("reviewed")]
    if len(reviewed) < MIN_REVIEWED:
        return Calibration(
            len(reviewed),
            None,
            None,
            False,
            f"only {len(reviewed)} clinician-reviewed labels; {MIN_REVIEWED} required",
        )
    human, judge = [h for h, _ in reviewed], [j for _, j in reviewed]
    agreement = round(sum(h == j for h, j in reviewed) / len(reviewed), 4)
    kappa = cohen_kappa(human, judge)
    ok = kappa >= MIN_KAPPA
    return Calibration(
        len(reviewed), agreement, kappa, ok, f"kappa {kappa} {'>=' if ok else '<'} {MIN_KAPPA}"
    )


async def judge_all(client: EgressChatClient, cases: list[dict[str, object]]) -> list[bool]:
    verdicts = []
    for c in cases:
        verdict = await client.ask_structured(
            ModelRequest(
                system=JUDGE_INSTRUCTIONS,
                user=f"Question: {c['question']}\nReport excerpt: {c['context']}\nAnswer: {c['answer']}",
                purpose="judge",
            ),
            Verdict,
        )
        verdicts.append(verdict.faithful)
    return verdicts


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preview",
        action="store_true",
        help="also compare the judge with the DRAFT labels: a review aid, never a calibration",
    )
    args = parser.parse_args()
    settings = get_settings()
    if settings.chat_provider == "fake":
        raise SystemExit("configure a real model (MEDPAL_CHAT_PROVIDER/MODEL/API_KEY) to run the judge")
    routes = build_model_routes(settings)
    cases = [json.loads(line) for line in SET.read_text().splitlines() if line.strip()]
    verdicts = await judge_all(EgressChatClient(routes["large"], routes=routes), cases)
    result = calibrate(cases, verdicts)
    print(f"judge agreement on reviewed labels: {result.agreement}  kappa: {result.kappa}  ({result.why})")
    print("CALIBRATED" if result.calibrated else "NOT CALIBRATED: do not use judge scores")
    if args.preview:
        drafts = [bool(c["faithful"]) for c in cases]
        agree = sum(d == v for d, v in zip(drafts, verdicts, strict=True)) / len(cases)
        print(
            f"\npreview against DRAFT labels (not a calibration): agreement {agree:.0%}, "
            f"kappa {cohen_kappa(drafts, verdicts)}  ({len(cases)} cases)"
        )
        for case, verdict in zip(cases, verdicts, strict=True):
            if bool(case["faithful"]) != verdict:
                print(f"  disagree {case['id']}: draft={case['faithful']} judge={verdict}  {case['answer']}")


if __name__ == "__main__":
    asyncio.run(main())
