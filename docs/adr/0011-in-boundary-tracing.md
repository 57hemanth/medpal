# ADR-0011: Tracing and cost metering stored in-boundary, metadata only

- **Status:** accepted
- **Context:** Every run should be traced: latency per node, model calls, tokens, cost. Traces usually contain prompts and retrieved text, which here means patient data. A hosted tracing service would be a second, unnamed egress path.
- **Options:**
  1. *LangSmith (hosted).* Excellent tooling, but prompts leave the boundary.
  2. *Langfuse, self-hosted.* Keeps data in, but brings several more services (ClickHouse, Redis, object storage) to run.
  3. **Our own spans in the Postgres we already run,** metadata only, behind a sink interface so an exporter can be added later.
- **Decision:** Option 3 (`services/platform/tracing.py`, table `trace_span`):
  - Graph nodes are timed by a LangChain callback; model calls are recorded by the egress client (model id, tokens, provider-reported or estimated and flagged, cost from configured prices with their price-list date).
  - The table has **no column that can hold text**. A trace-store failure never fails a request.
  - Metrics: `GET /api/ops/metrics` (compliance role) and `make cost-report`.
- **Revisit trigger:** a team needs trace UIs and evaluation workflows (add a self-hosted Langfuse exporter behind `SpanSink`, still in-boundary).
- **Consequences:**
  - *Easier:* no new infrastructure; traces can't leak content; cost per consultation comes from real runs.
  - *Harder:* no rich trace UI; structured-output token counts are usually estimated.
- **Proof:** `tests/unit/test_tracing.py` (node and model spans, priced and unpriced, no content in any field, failing sink tolerated) and `tests/integration/test_tracing_db.py` (API runs land in Postgres; metrics are compliance-only).
- **Checked on:** 2026-11-03
