# Implementation status

Reviewed against the code on 3 November 2026. **Verified** means a test in this repository proves it. **Written, unverified** means the code and tests exist but have not yet run against a live Postgres or Docker stack.

| Area | Implemented | Remaining |
|---|---|---|
| Web app | Role-based workspace: patient, caregiver, doctor, front desk and compliance each get a home dashboard and their own navigation; appointments, handoff queue, consultations, records, sharing, operations and audit-log pages; profile switcher in place of sign-in | Browser sign-in (OIDC); profiles are synthetic identities, not authentication |
| Triage and booking | Durable graph; red-flag rules with conservative negation; **structured safety screen** ([ADR-0010](adr/0010-structured-safety-screen.md)); specialty matching with one clarifying question; shortlist; explicit slot choice; idempotent booking; handoff tickets | Clinician sign-off on rules and wording; SMS delivery |
| Evaluations | `make eval`: gated sets (135 red-flag, 30 specialty, 60 records doctor-review) and held-out sets reported but never tuned; `make live-check`: real-model checks (records values and cited pages, refusals, routing, drafts, fallback, metering); LLM judge with Cohen's κ calibration on clinician-reviewed labels (agrees with all 20 draft labels on Gemini) | Clinician review of the calibration labels |
| Records | Upload with pre-storage privacy scan; doctor-review gate (rules + model `needs_doctor` flag) for advice questions; lay and Hinglish terms expanded to report terms in retrieval; **queued ingest** (arq on Redis, id only) with **parallel page processing** (LangGraph `Send`, bounded concurrency; [ADR-0009](adr/0009-async-ingest-parallel-pages.md)); RLS-scoped retrieval; explicit patient choice for caregivers; citation verification; safe degradation when the model is unavailable | Semantic embedding model; representative scan-quality evaluation |
| Scribe | Encounter creation for the doctor's own appointment; **review graph with doctor interrupt** (sign / edit / reject → redraft, max 2); every edit kept as a draft version; medicines grounded in the transcript; **pharmacy stock check** with staleness; signing writes the note and prescriptions in one transaction | Clinical evaluation of drafts |
| Pharmacy stock | One feed interface with CSV and real-time API adapters sharing contract tests; update-only sync where older readings never overwrite newer ones; 15-minute cron in the worker | A real pharmacy endpoint |
| Supervisor | `POST /api/assistant`: safety screen first; model labels clauses only (rules fallback); role-limited `Send` fan-out to triage, records and scribe as their own threads; follow-ups about this chat's appointment answered from the triage run's saved state; audited delegations; one trace ([ADR-0012](adr/0012-supervisor-with-specialist-graphs.md)) | — (the patient chat sends every new message through the assistant) |
| MCP tool server | `/mcp` (streamable HTTP) and stdio: `find_appointment_slots`, `book_appointment` (patient only, idempotent), `check_medicine_stock`; same identity resolver as the API | — |
| Models | Gemini verified live. Routing by tier (small/large, per-tier thinking level) with **fallback chains**; hard deadline per provider attempt; real token usage metered, thinking included; `ModelUnavailable` degrades to a human path | Production provider contracts |
| Deployment | **Hybrid boundary** ([ADR-0008](adr/0008-hybrid-deployment-egress-boundary.md)): internal network, nginx ingress, allowlisting CONNECT egress proxy, `make boundary-check` | Real cloud/on-premise target |
| Observability | **Tracing on every run** (graph nodes and model calls), in-boundary and metadata only ([ADR-0011](adr/0011-in-boundary-tracing.md)); operations dashboard and `/api/ops/metrics`; `make cost-report` from real spans; record reads linked to their trace in the audit log | Alerting |
| Load | `make load-test`: Poisson traffic at 1,400 requests/hour plus a 3× burst; p50/p95/p99 per endpoint against targets | A run with a real model provider |
| Privacy/security | Non-superuser RLS, Presidio de-identification, append-only audit, immutable notes, dev-auth production guard; [threat model](threat-model.md) | Rate limiting; encryption at rest and backups as deployment work |
| Retention/erasure | Audio is never persisted | Checkpoint expiry, patient erasure, object lifecycle |

## Validation

Run on 3 November 2026 against a live local stack, with Gemini: `gemini-4-argon` for note drafts, `gemini-3.8-flash` for records answers, routing and as the fallback.

| Check | Result |
|---|---|
| Unit tests | 240 passed |
| Data tests | 64 passed |
| Web tests and production build | 9 passed; build clean |
| Lint, format, mypy, module-boundary contracts | clean |
| Evaluation gates (`make eval`) | red-flag recall 100%, over-triage 2%, specialty 100%; records doctor-review recall 100%, over-refusal 0%. Held-out sets reported, never tuned: red-flag rules 20% (the safety questions cover the rest), doctor-review rules 30% |
| Integration tests (real Postgres) | 61 passed |
| Live API check (smoke) | 62/62 on Gemini |
| Real-model check (`make live-check`) | 40/40: records values and cited pages (including Hinglish), refusals, held-out advice questions 10/10 with rules + model flag and 0/10 plain questions refused, routing 5/5 by the model, emergency never reaches the model, scribe drafts invent no medicines, broken primary falls through to the fallback, every call priced |
| Provider failure in the wild | `gemini-4-argon` returned 504 during the run; the fallback answered and the patient saw no error |
| LLM judge | agrees with all 20 draft labels (κ 1.0); **not calibrated** until 20 labels are clinician-reviewed |
| Load test, 1,400 req/h then 3× burst, real model | **All targets met**, 0% errors: records answers p95 3.6 s (target 8 s), assistant p95 5.8 s (target 10 s), triage, safety questions and booking p95 under 30 ms |
| Cost from real traces | $0.0020 per consultation (formula in the cost report); every call priced, real token counts including thinking, none estimated |
| Full application image | builds |
| Deployment boundary | direct internet blocked; non-allowlisted host refused; allowlisted model API reachable |

### Decision: records answers on the faster model

Measured on the same live check and the same load test, changing only `MEDPAL_RECORDS_MODEL_TIER`:

| | `gemini-4-argon` (large) | `gemini-3.8-flash` (small) |
|---|---|---|
| `make live-check` | 40/40 | 40/40 |
| Records answer, average (sequential) | 8.7 s | 2.0 s |
| Records answer p95 under burst | 14.0 s (misses 8 s) | 3.6 s |
| Assistant p95 under burst | 10.6 s (misses 10 s) | 5.8 s |
| Cost per records answer | $0.00133 | $0.00035 |

Same quality on every check, about 4× faster at the tail and about 4× cheaper, so records answers use the small tier. Note drafts stay on the large model: they are longer, less latency-sensitive (the doctor reviews them), and the scribe checks pass on it. Re-run both measurements before changing either choice.

Runtime instructions: [adapter setup](adapters.md). Architecture: [request flow](architecture.md).
