"""Cost sheet from real traces: what one consultation costs to run, with the formula shown.

    uv run python -m infra.scripts.cost_report [--hours 24] [--answers-per-consult 2]

Reads trace_span (metadata only) as the owner role and writes evals/runs/cost-<timestamp>.md.
"""

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from services.platform.config import get_settings
from services.platform.metrics import COST_FORMULA, collect


def _fmt(value: object, digits: int = 1) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--answers-per-consult", type=float, default=2.0)
    args = parser.parse_args()
    settings = get_settings()
    async with await psycopg.AsyncConnection.connect(
        settings.migration_database_url, row_factory=dict_row
    ) as conn:
        data = await collect(conn, hours=args.hours)

    cur = settings.price_currency
    lines = [f"# Cost sheet ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC, last {args.hours} h)", ""]
    lines += ["## Runs", "", "| Workflow | Runs | p50 ms | p95 ms | Error rate |", "|---|---|---|---|---|"]
    lines += [
        f"| {r['workflow']} | {r['runs']} | {_fmt(r['p50_ms'])} | {_fmt(r['p95_ms'])}"
        f" | {_fmt(r['error_rate'], 3)} |"
        for r in data["runs"]
    ]
    lines += [
        "",
        "## Model calls",
        "",
        f"| Workflow | Model | Calls | Tokens in | Tokens out | Estimated? | Cost ({cur}) | Price list |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {m['workflow']} | {m['model']} | {m['calls']} | {m['tokens_in']} | {m['tokens_out']} |"
        f" {'yes' if m['tokens_estimated'] else 'no'}"
        f" | {_fmt(m['cost'], 6) if not m['unpriced_calls'] else 'unpriced'}"
        f" | {m['price_list_date'] or '—'} |"
        for m in data["models"]
    ]
    per_run = data["cost_per_run"]
    parts = [per_run.get("triage"), per_run.get("records"), per_run.get("scribe")]
    if any(p is None for p in parts):
        total = "not computable: some workflows have no runs or unpriced model calls in this window"
    else:
        value = parts[0] + args.answers_per_consult * parts[1] + parts[2]  # type: ignore[operator]
        total = f"{value:.6f} {cur}"
    lines += [
        "",
        "## Cost per consultation",
        "",
        f"Formula: {COST_FORMULA}.",
        f"Answers per consultation assumed: {args.answers_per_consult}.",
        "",
        *[f"- avg {k} run: {_fmt(v, 6)} {cur}" for k, v in per_run.items()],
        "",
        f"**Cost per consultation: {total}**",
        "",
    ]
    out = Path("evals/runs") / f"cost-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    asyncio.run(main())
