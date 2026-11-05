# Implementation status

Reviewed against the code on 3 November 2026. **Verified** means a test in this repository proves it. **Written, unverified** means the code and tests exist but have not yet run against a live Postgres or Docker stack.

| Area | Implemented | Remaining |
|---|---|---|
| Test access | Login page offers seeded patient, caregiver, doctor, desk and compliance identities | Browser OIDC deferred; test identities are not production authentication |
| Triage and booking | Durable graph; red-flag rules with conservative negation; **structured safety screen** ([ADR-0010](adr/0010-structured-safety-screen.md)); specialty matching with one clarifying question; shortlist; explicit slot choice; idempotent booking; handoff tickets | Clinician sign-off on rules and wording; SMS delivery |
| Evaluations | `make eval`: gated sets (135 red-flag, 30 specialty) and a held-out set reported but never tuned; LLM-as-judge harness with Cohen's κ calibration on clinician-reviewed labels | Clinician review of the calibration labels; a real model key to run the judge |
| Records | Upload with pre-storage privacy scan; **queued ingest** (arq on Redis, id only) with **parallel page processing** (LangGraph `Send`, bounded concurrency; [ADR-0009](adr/0009-async-ingest-parallel-pages.md)); RLS-scoped retrieval; explicit patient choice for caregivers; citation verification; safe degradation when the model is unavailable | Semantic embedding model; representative scan-quality evaluation |
| Scribe | Encounter creation for the doctor's own appointment; **review graph with doctor interrupt** (sign / edit / reject → redraft, max 2); every edit kept as a draft version; medicines grounded in the transcript; **pharmacy stock check** with staleness; signing writes the note and prescriptions in one transaction | Clinical evaluation of drafts |
| Pharmacy stock | One feed interface with CSV and real-time API adapters sharing contract tests; update-only sync where older readings never overwrite newer ones; 15-minute cron in the worker | A real pharmacy endpoint |
| MCP tool server | `/mcp` (streamable HTTP) and stdio: `find_appointment_slots`, `book_appointment` (patient only, idempotent), `check_medicine_stock`; same identity resolver as the API | — |
| Models | Routing by tier (small/large) with **fallback chains** across providers; `ModelUnavailable` degrades to a human path | Production provider contracts |
| Deployment | **Hybrid boundary** ([ADR-0008](adr/0008-hybrid-deployment-egress-boundary.md)): internal network, nginx ingress, allowlisting CONNECT egress proxy, `make boundary-check` | Real cloud/on-premise target |
| Observability | **Tracing on every run** (graph nodes and model calls), in-boundary and metadata only ([ADR-0011](adr/0011-in-boundary-tracing.md)); `/api/ops/metrics`; `make cost-report` from real spans | Trace UI |
| Load | `make load-test`: Poisson traffic at 1,400 requests/hour plus a 3× burst; p50/p95/p99 per endpoint against targets | A recorded run (needs the stack) |
| Privacy/security | Non-superuser RLS, Presidio de-identification, append-only audit, immutable notes, dev-auth production guard; [threat model](threat-model.md) | Rate limiting; encryption at rest and backups as deployment work |
| Retention/erasure | Audio is never persisted | Checkpoint expiry, patient erasure, object lifecycle |

## Validation

| Check | Result |
|---|---|
| Unit tests | 200 passed |
| Data tests | 64 passed |
| Web tests | 4 passed |
| Lint, format, mypy, module-boundary contracts | clean |
| Evaluation gates | recall 100%, over-triage 2%, specialty 100% (held-out rule recall reported separately) |
| Integration tests (real Postgres) | 49 written; the 40 from the previous release passed; the new ones (red team, scribe, ingest queue, tracing, MCP) are **written, unverified** |
| Live stack: image build, boundary check, load test, cost report | **unverified**: the local Docker engine failed during this change |

Runtime instructions: [adapter setup](adapters.md). Architecture: [request flow](architecture.md).
