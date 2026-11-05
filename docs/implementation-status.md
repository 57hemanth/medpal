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
| Load | `make load-test`: Poisson traffic at 1,400 requests/hour plus a 3× burst; p50/p95/p99 per endpoint against targets | A run with a real model provider |
| Privacy/security | Non-superuser RLS, Presidio de-identification, append-only audit, immutable notes, dev-auth production guard; [threat model](threat-model.md) | Rate limiting; encryption at rest and backups as deployment work |
| Retention/erasure | Audio is never persisted | Checkpoint expiry, patient erasure, object lifecycle |

## Validation

Run on 3 November 2026 against a live local stack.

| Check | Result |
|---|---|
| Unit tests | 202 passed |
| Data tests | 64 passed |
| Web tests and production build | 4 passed; build clean |
| Lint, format, mypy, module-boundary contracts | clean |
| Evaluation gates | recall 100%, over-triage 2%, specialty 100%; held-out rule recall 20% (reported, not a gate; the safety screen covers it) |
| Integration tests (real Postgres) | 52 passed: RLS, booking concurrency, red team, scribe signing, queued ingest, tracing, MCP |
| Live API check | 55/55: triage with safety screen, booking, records, consent, scribe review/edit/sign, MCP tools, metrics |
| Queued ingest with a real worker | upload returns `queued`; the arq worker completes it; the answer cites the right page |
| Load test (1,400 req/h for 2 min, then 3× for 1 min) | 0% errors; p95 triage 20–33 ms, records 96 ms. **Measured with the local fake model**, so these are the app's and database's own latencies; real model time comes on top |
| Cost report | works from real spans; cost per consultation is reported as *not computable* until a priced model is configured, rather than estimated |
| Full application image | builds |
| Deployment boundary (`make up-boundary`, `make boundary-check`) | direct internet blocked; non-allowlisted host refused (403); allowlisted model API reachable (200) |

Runtime instructions: [adapter setup](adapters.md). Architecture: [request flow](architecture.md).
