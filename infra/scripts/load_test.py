"""Load test against a running API: the target rate, then a burst, with p95s per endpoint.

    uv run python -m infra.scripts.load_test --base http://localhost:8000 --rate 1400 --minutes 5 --burst 3

Traffic is a realistic mix played by the seeded dev users: a triage start, its safety-screen answers,
a booking (each with its own idempotency key), a multi-part assistant message, a records question,
and a front-desk queue read.
Requests are fired on a Poisson schedule at the target hourly rate, then at `burst` times that rate
(a morning rush). Results: p50/p95/p99 and error rate per endpoint, checked against the latency targets,
written to evals/runs/load-<timestamp>.md. Exit code 1 if a target or the error budget is missed.
"""

import argparse
import asyncio
import random
import statistics
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

U = "00000000-0000-0000-0000-0000000"
PATIENTS = [
    {"X-Dev-User-Id": U + "e0001", "X-Dev-Role": "patient", "X-Dev-Patient-Id": U + "b0001"},
    {"X-Dev-User-Id": U + "e0002", "X-Dev-Role": "patient", "X-Dev-Patient-Id": U + "b0002"},
]
DESK = {"X-Dev-User-Id": U + "e0003", "X-Dev-Role": "desk"}
SYMPTOMS = [
    "knee pain for a week",
    "itchy rash on legs",
    "cough at night for a week",
    "acidity after meals",
    "frequent headaches",
    "mild fever and body ache",
    "sore throat and ear pain",
]
TARGET_P95_MS = {
    "triage.start": 4000,
    "triage.safety": 4000,
    "triage.book": 4000,
    "records.question": 8000,
    "assistant": 10000,  # routing model + specialists in parallel
}
MIXED = [
    "My knee has hurt for a week. Also, what was my LDL last time?",
    "I have a skin rash, and can you tell me my HbA1c?",
    "frequent headaches in the evening",
]
MAX_ERROR_RATE = 0.01

samples: dict[str, list[float]] = defaultdict(list)
errors: dict[str, int] = defaultdict(int)


async def timed(name: str, call) -> httpx.Response | None:  # type: ignore[no-untyped-def]
    start = time.perf_counter()
    try:
        response = await call()
    except httpx.HTTPError:
        errors[name] += 1
        return None
    samples[name].append((time.perf_counter() - start) * 1000)
    if response.status_code >= 500:
        errors[name] += 1
    return response


async def patient_journey(client: httpx.AsyncClient) -> None:
    h = random.choice(PATIENTS)
    start = await timed(
        "triage.start", lambda: client.post("/triage", headers=h, json={"text": random.choice(SYMPTOMS)})
    )
    if start is None or start.status_code != 200:
        return
    body = start.json()
    if body.get("status") == "awaiting_safety_check":
        answers = {q["key"]: False for q in body["safety_questions"]}
        r = await timed(
            "triage.safety",
            lambda: client.post(
                f"/triage/{body['thread_id']}/resume", headers=h, json={"safety_answers": answers}
            ),
        )
        if r is None or r.status_code != 200:
            return
        body = r.json()
    if body.get("status") == "awaiting_choice" and body.get("candidates"):
        slot = body["candidates"][0]["slot_id"]
        await timed(
            "triage.book",
            lambda: client.post(
                f"/triage/{body['thread_id']}/resume",
                headers=h,
                json={"slot_id": slot, "idempotency_key": f"load-{uuid.uuid4()}"},
            ),
        )


async def records_question(client: httpx.AsyncClient) -> None:
    h = random.choice(PATIENTS)
    await timed(
        "records.question",
        lambda: client.post("/api/records/questions", headers=h, json={"question": "What was my LDL?"}),
    )


async def assistant(client: httpx.AsyncClient) -> None:
    h = random.choice(PATIENTS)
    await timed(
        "assistant", lambda: client.post("/api/assistant", headers=h, json={"message": random.choice(MIXED)})
    )


async def desk_queue(client: httpx.AsyncClient) -> None:
    await timed("desk.handoffs", lambda: client.get("/api/front-desk/handoffs", headers=DESK))


async def phase(client: httpx.AsyncClient, per_hour: float, seconds: float) -> None:
    rate = per_hour / 3600.0
    deadline, tasks = time.monotonic() + seconds, []
    while time.monotonic() < deadline:
        await asyncio.sleep(random.expovariate(rate))
        roll = random.random()
        job = (
            patient_journey
            if roll < 0.55
            else assistant
            if roll < 0.75
            else records_question
            if roll < 0.9
            else desk_queue
        )
        tasks.append(asyncio.create_task(job(client)))
    await asyncio.gather(*tasks)


def pct(values: list[float], q: float) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[q - 1] if len(values) > 1 else values[0]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--rate", type=float, default=1400, help="requests per hour at steady state")
    parser.add_argument("--minutes", type=float, default=5)
    parser.add_argument("--burst", type=float, default=3, help="burst multiplier for the second phase")
    args = parser.parse_args()
    async with httpx.AsyncClient(base_url=args.base, timeout=60) as client:
        await phase(client, args.rate, args.minutes * 60)
        await phase(client, args.rate * args.burst, args.minutes * 60 / 2)

    rows, failed = [], []
    for name in sorted(samples.keys() | errors.keys()):
        values = samples.get(name, [])
        total = len(values) + (errors[name] if not values else 0)
        err_rate = errors[name] / max(len(values), total, 1)
        p95 = pct(values, 95) if values else None
        target = TARGET_P95_MS.get(name)
        ok = (p95 is not None and (target is None or p95 <= target)) and err_rate <= MAX_ERROR_RATE
        if not ok:
            failed.append(name)
        rows.append(
            f"| {name} | {len(values)} | {pct(values, 50):.0f} | {p95:.0f} | {pct(values, 99):.0f} |"
            f" {target or '—'} | {err_rate:.2%} | {'PASS' if ok else 'FAIL'} |"
            if values
            else f"| {name} | 0 | — | — | — | {target or '—'} | {err_rate:.2%} | FAIL |"
        )
    report = [
        f"# Load test ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)",
        "",
        f"Steady {args.rate:.0f}/h for {args.minutes} min,"
        f" then {args.burst}× burst for {args.minutes / 2} min,"
        f" against {args.base}.",
        "",
        "| Endpoint | Requests | p50 ms | p95 ms | p99 ms | Target p95 ms | Errors | Result |",
        "|---|---|---|---|---|---|---|---|",
        *rows,
        "",
    ]
    out = Path("evals/runs") / f"load-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(report))
    print("\n".join(report))
    print(f"written to {out}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
