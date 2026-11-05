"""Operational metrics from the in-boundary trace store: latency percentiles, errors, tokens, cost.

Every number is a query over recorded spans; a metric with no data is reported as missing, not as zero.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from psycopg import AsyncConnection

from .tracing import RUN_SPAN

COST_FORMULA = (
    "cost per consultation = avg cost of a triage run + answers_per_consult × avg cost of a records answer"
    " + avg cost of a scribe run (+ ingest per uploaded document)"
)


async def collect(conn: AsyncConnection, *, hours: int = 24) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    runs = await (
        await conn.execute(
            """
            SELECT workflow, count(*) AS runs,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms,
                   avg((status = 'error')::int)::float8 AS error_rate
              FROM trace_span WHERE kind = 'node' AND name = %s AND started_at >= %s
             GROUP BY workflow ORDER BY workflow
            """,
            (RUN_SPAN, since),
        )
    ).fetchall()
    nodes = await (
        await conn.execute(
            """
            SELECT workflow, name, count(*) AS calls,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms
              FROM trace_span WHERE kind = 'node' AND name <> %s AND started_at >= %s
             GROUP BY workflow, name ORDER BY p95_ms DESC LIMIT 20
            """,
            (RUN_SPAN, since),
        )
    ).fetchall()
    models = await (
        await conn.execute(
            """
            SELECT workflow, name AS model, count(*) AS calls,
                   avg((status = 'error')::int)::float8 AS error_rate,
                   sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out,
                   bool_or(tokens_estimated) AS tokens_estimated,
                   sum(cost) AS cost,
                   count(*) FILTER (WHERE cost IS NULL AND status = 'ok') AS unpriced_calls,
                   max(price_list_date) AS price_list_date,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms
              FROM trace_span WHERE kind = 'model' AND started_at >= %s
             GROUP BY workflow, name ORDER BY workflow, model
            """,
            (since,),
        )
    ).fetchall()
    run_rows = cast(list[dict[str, Any]], runs)
    model_rows = cast(list[dict[str, Any]], models)
    runs_by = {r["workflow"]: r["runs"] for r in run_rows}
    cost_per_run: dict[str, float | None] = {}
    for workflow, count in runs_by.items():
        priced = [m for m in model_rows if m["workflow"] == workflow]
        if any(m["unpriced_calls"] for m in priced):
            cost_per_run[workflow] = None  # some calls have no price: do not pretend a total
        else:
            total = sum(float(m["cost"] or 0) for m in priced)
            cost_per_run[workflow] = round(total / count, 6) if count else None
    return {
        "window_hours": hours,
        "runs": run_rows,
        "slowest_nodes": cast(list[dict[str, Any]], nodes),
        "models": model_rows,
        "cost_per_run": cost_per_run,
        "cost_formula": COST_FORMULA,
    }
