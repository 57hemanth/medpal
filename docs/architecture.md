# How MedPal works

This guide walks through the system from a request coming in to a row being written, and explains why each piece is there. Design decisions link to their [ADRs](adr/). Anything not yet built is marked **(planned)**.

## 1. The big picture

```
 Patient app / Front desk / Doctor console           (React SPA)
                    │
                    ▼
 ┌──────────────── FastAPI (services/api) ─────────────────────────────────┐
 │  auth dependency → AuthContext {user_id, role, acting_for_patient_id}   │
 │  routers: /triage, /api/{records,scribe,consents,...}                  │
 └───────────────┬──────────────────────────────────────────────────────────┘
                 ▼
 ┌──────── LangGraph graphs (services/agent) ───────┐   ┌── platform (services/platform) ──┐
 │ triage: intake → red-flag gate → specialty →     │──►│ db pools + scoped() RLS sessions │
 │         shortlist → interrupt(patient picks) →   │   │ audit writer (append-only)       │
 │         book → notify                            │   │ phi/ Presidio de-identification  │
 └───────┬──────────────────────────────────────────┘   │ config, auth context             │
         │ checkpoints (langgraph schema)               └──────────────────────────────────┘
         ▼                                 ▲
 ┌──────────────────── PostgreSQL 17 + pgvector ────────────────────────────┐
 │ scheduling: clinic, doctor, slot, appointment, handoff_ticket           │
 │ records: document, doc_chunk (vector(1024) + tsvector), consent         │
 │ clinical: encounter, note_version (immutable), prescription             │
 │ audit_event (append-only, partitioned)  ·  row-level security on PHI    │
 └──────────────────────────────────────────────────────────────────────────┘
```

It's one deployable service with strict module boundaries ([ADR-0001](adr/0001-modular-monolith.md)). `import-linter` stops the workflow modules from importing each other, and stops the platform layer from depending on any workflow.

## 2. A triage request, step by step

`POST /triage {"text": "knee pain for a week"}` with the caller's identity.

1. **Identity.** `services/api/deps.py` builds an `AuthContext`. In development it trusts `X-Dev-*` headers, a mode that refuses to start when `MEDPAL_ENV=prod`; OIDC bearer verification is implemented; browser login intentionally uses selectable synthetic test identities. From here on, **who** the caller is comes only from this context, never from request text or model output. That closes the "book for patient 123" prompt-injection route.
2. **A new run.** The router creates a `thread_id` and invokes the compiled graph with `{auth, intake_text}`. The API keeps no state; everything lives in the LangGraph checkpointer in Postgres ([ADR-0002](adr/0002-orchestration-langgraph.md)).
3. **Red-flag gate, before anything else.** `red_flag_rules` checks the text for emergency presentations, in English and Hinglish ("seene mein dard" = chest pain). On a match the run goes to `emergency_handoff`: it opens a ticket in the emergency queue, replies with fixed guidance (call 112), and ends. **No diagnosis, no AI, and it works even if every model is down.** Clearly negated phrases ("no chest pain") are ignored, conservatively: an un-negated mention anywhere still fires.
4. **Structured safety screen.** Free-text rules don't generalise to every way a person describes an emergency, so every routine run pauses with `interrupt("safety_check")` and asks seven explicit yes/no questions (chest pain, breathing, unconscious or fits, stroke signs, heavy bleeding, poisoning, self-harm). Any "yes" goes to `emergency_handoff`; incomplete answers are asked again ([ADR-0010](adr/0010-structured-safety-screen.md)). `make eval` gates the rules on recall 100% and over-triage ≤ 10%, and reports a held-out set it is never tuned on.
5. **Specialty.** `match_specialty` picks one of 38 specialties with a deterministic phrase matcher. If confidence is low, `ask_clarifying` asks one question (`interrupt("clarify")`); still unclear, the run goes to the front desk.
6. **Shortlist** (plain SQL, no AI). `services/scheduling/service.py::shortlist` returns each doctor's earliest **free** slot, ranked by:
   - same city as the patient (a filter);
   - doctor speaks the patient's language;
   - the patient's preferred clinic;
   - soonest slot.

   The patient's preferences are read **as the caller** under row-level security, so the tool can't read anyone else's profile. The query uses `LATERAL … LIMIT 1` per doctor, so each doctor's index scan stops at the first free slot: **4.5 ms vs 60 ms** for the naive version on 480k slots with 6,200 bookings.
7. **Pause for the patient.** `present_options` calls `interrupt({"candidates": …})`. The run is checkpointed and the API returns `awaiting_choice` with three options, times shown in clinic local time ("Mon 9 Nov, 08:00").
8. **Resume.** `POST /triage/{thread_id}/resume {slot_id, idempotency_key}`. The router first checks the thread belongs to the caller: a thread id is not an authorisation. The graph accepts the choice only if it was one of the offered slots. Any replica can resume, because the state comes from Postgres.
9. **Book.** `reserve()` runs one transaction:
   - an advisory lock on the slot;
   - booked count < capacity?
   - insert the appointment with the client's idempotency key;
   - write the audit event.

   A retry with the same key returns the same booking. A full slot sends the graph back to the shortlist with that slot excluded, up to three times, then to the front desk ([ADR-0005](adr/0005-booking-concurrency.md)).
10. **Notify.** A fixed-template confirmation. *SMS delivery is planned; model text will never go into an SMS.*

**Why the booking step sits in its own node:** a node that calls `interrupt()` runs again from the top when it resumes. Anything with side effects in that node would happen twice, so booking lives in the next node.

## 3. Who can see what: row-level security

Patient data is isolated **by the database**, not by remembering a `WHERE` clause ([ADR-0003](adr/0003-row-level-security.md)).

| Caller | Clinical records visible |
|---|---|
| Patient | their own |
| Caregiver | patients who granted unexpired, unrevoked `records:read` consent |
| Doctor | patients with an appointment with them |
| Front desk | demographics only, no clinical content |
| Compliance | audit trail and signed notes |
| System worker | everything (ingest), and the only role that writes chunks |

How it works:
- `scoped(pool, auth)` opens a transaction and sets `app.user_id` / `app.role` locally to it. Every policy calls one function, `app_allowed_patients()`. With no identity set, no rows come back.
- The app connects as `medpal_app`, which is **not a superuser**. This matters because superusers bypass RLS entirely. Migrations and seeding use the owner role.
- Grants limit verbs and columns too:
  - a patient can revoke a consent but not extend it;
  - the app can't change slot capacity;
  - signed notes and audit rows can't be updated or deleted, even by the owner.

## 4. What may leave the boundary: de-identification

Identified data stays inside the deployment. Before any text goes to an external model, `services/platform/phi/` runs Microsoft Presidio, extended for India ([ADR-0006](adr/0006-presidio-deidentification.md)):

```
"meri maa Asha Verma ko seene mein dard hai, mobile 98765 43210"
        │ tokenise (known identities + India recognisers + Hinglish mode)
        ▼
"meri maa <PERSON_1> ko seene mein dard hai, mobile <IN_PHONE_1>"   ──► external model
        │ assert_clean (independent second pass, fails closed)
        ▼
model reply with tokens ──► reidentify (token map never leaves) ──► patient
```

- Names, phones, ABHA, PAN, MRN, a labelled date of birth and locations are **tokenised**; Aadhaar is **blocked**. Lab values, drug names and report dates are **kept**, because the model needs them.
- Tested in both directions: no leaks, and no over-scrubbing of clinical text, including Hinglish.

Workflows call `EgressChatClient`, which de-identifies before invocation. Requests name a **tier** (`small` for routing and clarification, `large` for drafting and Q&A); each tier is a chain of providers tried in order, so one vendor outage falls back to the next. If every provider fails or returns malformed output, `ModelUnavailable` sends the workflow down a human path instead of returning an error. The local fake model remains the development default.

A second, structural control sits underneath the scrubber ([ADR-0008](adr/0008-hybrid-deployment-egress-boundary.md)). In the boundary topology (`make up-boundary`), the API, worker, Postgres and Redis share an internal network with no route out. The only exit is an allowlisting `CONNECT` proxy to the configured model hosts. `make boundary-check` proves this from inside the API container.

## 5. Audit

Every write that touches patient data (bookings, handoff tickets) writes an `audit_event` **in the same transaction**: actor, role, action, record, patient, purpose, trace id. The table is partitioned by month and append-only. "Who saw this record?" is a single query. Records Q&A writes read-audit events for cited chunks.

## 6. Data

- **Generated network** ([ADR-0004](adr/0004-generated-directory-in-code.md)): 6 hospitals and 22 clinics in Pune and Hyderabad, 38 specialties, 500 doctors and 480,000 slots, produced by seeded code. `make seed` loads it with `COPY` in about 4 seconds.
- **Public datasets:** sources, licences and cleaning are in [`data/README.md`](../data/README.md).
- **Per-table reference:** [`docs/data-model/`](data-model/).

## 7. How it's tested

| Layer | What | Where |
|---|---|---|
| Unit | Graph paths with fake tools and the in-memory checkpointer; API contract; de-identification (66 cases) | `tests/unit/` |
| Data | Cleaning checks with drop reasons tallied; generated-layer rules | `data/transforms/tests/`, `data/synthetic/tests/` |
| Integration | Real Postgres: concurrency, idempotency, every RLS role, append-only audit and notes, resume on a fresh app instance, shortlist ranking | `tests/integration/` |

Integration tests rebuild a throwaway `medpal_test` database from migrations on every run. Fixtures are set up with the owner role; the code under test runs as the app role, so RLS is exercised for real.

## 8. Records and scribe adapters

Records upload validates the entire extracted text for blocked identifiers **before storage**.
Text PDFs are extracted with pypdf; empty-text pages fall back to local Poppler/Tesseract OCR
(English + Hindi). Extraction preserves page numbers in chunks and citations. Unreadable,
encrypted, empty or oversized documents are rejected rather than saved unchecked.

Indexing runs on a queue ([ADR-0009](adr/0009-async-ingest-parallel-pages.md)): the upload enqueues
only the document id, and the arq worker (`make worker`) runs the ingest graph. The graph fans out
one `Send` per page under `MEDPAL_INGEST_MAX_CONCURRENCY`, then writes all chunks in one transaction.
`MEDPAL_INGEST_MODE=inline` runs the same graph in the request for local development.

Local development uses private filesystem objects; the container mounts a named volume.
Deployments can use an S3-compatible store with server-side encryption. Memory storage is
available for tests; production requires S3. Object keys use patient id + content digest rather
than original filenames. Identified storage must be provisioned inside the deployment boundary.

The scribe accepts typed transcripts and optional PCM WAV uploads. With the `speech` extra and
a pre-provisioned faster-whisper model directory, audio is transcribed locally, without runtime
model downloads or persistent audio storage. The scribe is a LangGraph with a doctor interrupt:

```
draft_note → ground_medicines → stock_check → review (interrupt)
   ▲                                │ sign   → persist (note + prescriptions, one transaction)
   └── reject (max 2 redrafts) ─────┤ edit   → stock_check again → review
                                    │ reject after 2 → doctor writes it by hand
```

A medicine is kept only if it is named in the transcript; rejected ones are shown to the doctor.
The stock check reads `medicine_stock` and flags *in stock*, *out of stock*, *stale* (more than
48 hours old) or *not in formulary*, always with the reading's time. Stock is kept current by
feed adapters (nightly CSV or a real-time API) that the worker syncs every 15 minutes.

The same scheduling and stock operations are exposed to other agents as an **MCP tool server**
at `/mcp`, using the same identity resolver as the API. No tool takes a patient id.

## 9. Tracing and cost

Every graph run and model call writes spans to `trace_span` in Postgres
([ADR-0011](adr/0011-in-boundary-tracing.md)): node timings, model id, tokens and cost from the
configured price list. The table has no column that can hold text. `GET /api/ops/metrics`
(compliance role) gives p50/p95 per workflow, the slowest nodes and cost per run;
`make cost-report` writes the cost sheet; `make load-test` drives 1,400 requests/hour plus a burst
and checks p95s against targets.

See [implementation status](implementation-status.md) for the full distinction between API,
UI, configuration and unfinished scope, and [adapter setup](adapters.md) for runtime instructions.

## 10. Remaining work

- Clinician sign-off on the emergency rules, safety-screen wording and specialty list.
- Production self-hosted multilingual embeddings (the current embedding adapter is deterministic).
- Checkpoint retention and patient erasure workflows; rate limiting.
- Booking overrides and fixed-template SMS delivery.
- Browser consent granting and a compliance console.
- Browser OIDC login is deferred by choice; the backend bearer verifier remains available.
